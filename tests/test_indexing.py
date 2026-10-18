import hashlib
import time

import pytest

from sbesm.db import FileRow, connect, get_file_row
from sbesm.indexing import (
    Classification,
    ClassifiedEntry,
    classify,
    has_findings,
    render_preview,
    run_index,
)
from sbesm.migrations import MIGRATIONS, apply_migrations
from sbesm.scanner import ScannedEntry


def _make_storage(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    sbesm_dir = root / ".sbesm"
    sbesm_dir.mkdir()
    db_path = sbesm_dir / "index.sqlite"
    conn = connect(db_path)
    apply_migrations(conn, MIGRATIONS)
    conn.close()
    return root, db_path


def _write_and_scan(tmp_path, name: str, content: bytes) -> ScannedEntry:
    path = tmp_path / name
    path.write_bytes(content)
    st = path.lstat()
    return ScannedEntry(name, "regular", st.st_size, st.st_mtime_ns, path)


_BASE_ROW_KWARGS = {
    "hashed_at": "t",
    "last_seen_at": "t",
    "state": "indexed",
    "candidate_sha256": None,
}


# --- 2.4.1 classification truth table ---------------------------------------


def test_classify_new_file_hashes_by_default(tmp_path):
    scanned = _write_and_scan(tmp_path, "a.txt", b"hello")
    result = classify(scanned, existing=None)
    assert result.classification == Classification.NEW
    assert result.computed_hash == hashlib.sha256(b"hello").hexdigest()


def test_classify_new_file_plan_only_skips_hash(tmp_path):
    scanned = _write_and_scan(tmp_path, "a.txt", b"hello")
    result = classify(scanned, existing=None, allow_hashing=False)
    assert result.classification == Classification.NEW
    assert result.computed_hash is None


def test_classify_unchanged_when_metadata_matches(tmp_path):
    scanned = _write_and_scan(tmp_path, "a.txt", b"hello")
    existing = FileRow(
        path="a.txt",
        kind="regular",
        size=scanned.size,
        mtime_ns=scanned.mtime_ns,
        reference_sha256="deadbeef",
        reference_size=scanned.size,
        reference_mtime_ns=scanned.mtime_ns,
        **_BASE_ROW_KWARGS,
    )
    result = classify(scanned, existing)
    assert result.classification == Classification.UNCHANGED
    assert result.computed_hash is None


def test_classify_changed_same_hash_refreshes_metadata_only(tmp_path):
    content = b"hello"
    digest = hashlib.sha256(content).hexdigest()
    scanned = _write_and_scan(tmp_path, "a.txt", content)
    existing = FileRow(
        path="a.txt",
        kind="regular",
        size=999,
        mtime_ns=111,
        reference_sha256=digest,
        reference_size=999,
        reference_mtime_ns=111,
        **_BASE_ROW_KWARGS,
    )
    result = classify(scanned, existing)
    assert result.classification == Classification.CHANGED_SAME_HASH
    assert result.computed_hash == digest


def test_classify_changed_conflict_when_hash_differs(tmp_path):
    scanned = _write_and_scan(tmp_path, "a.txt", b"new content")
    existing = FileRow(
        path="a.txt",
        kind="regular",
        size=1,
        mtime_ns=1,
        reference_sha256="old-hash-value",
        reference_size=1,
        reference_mtime_ns=1,
        **_BASE_ROW_KWARGS,
    )
    result = classify(scanned, existing)
    assert result.classification == Classification.CHANGED_CONFLICT
    assert result.computed_hash != "old-hash-value"


def test_classify_changed_unknown_under_plan_only(tmp_path):
    scanned = _write_and_scan(tmp_path, "a.txt", b"new content")
    existing = FileRow(
        path="a.txt",
        kind="regular",
        size=1,
        mtime_ns=1,
        reference_sha256="old-hash-value",
        reference_size=1,
        reference_mtime_ns=1,
        **_BASE_ROW_KWARGS,
    )
    result = classify(scanned, existing, allow_hashing=False)
    assert result.classification == Classification.CHANGED_UNKNOWN
    assert result.computed_hash is None


def test_classify_missing_when_not_scanned():
    existing = FileRow(
        path="gone.txt",
        kind="regular",
        size=1,
        mtime_ns=1,
        reference_sha256="h",
        reference_size=1,
        reference_mtime_ns=1,
        **_BASE_ROW_KWARGS,
    )
    result = classify(None, existing)
    assert result.classification == Classification.MISSING


def test_classify_unreadable(tmp_path):
    scanned = ScannedEntry("bad.txt", "unreadable", None, None, tmp_path / "bad.txt")
    result = classify(scanned, existing=None)
    assert result.classification == Classification.UNREADABLE


def test_classify_rehash_forces_hash_even_when_metadata_unchanged(tmp_path):
    content = b"hello"
    digest = hashlib.sha256(content).hexdigest()
    scanned = _write_and_scan(tmp_path, "a.txt", content)
    existing = FileRow(
        path="a.txt",
        kind="regular",
        size=scanned.size,
        mtime_ns=scanned.mtime_ns,
        reference_sha256=digest,
        reference_size=scanned.size,
        reference_mtime_ns=scanned.mtime_ns,
        **_BASE_ROW_KWARGS,
    )
    result = classify(scanned, existing, force_rehash=True)
    assert result.classification == Classification.CHANGED_SAME_HASH
    assert result.computed_hash == digest


def test_classify_symlink_new_unchanged_and_target_changed(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("x")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    st = link.lstat()
    scanned = ScannedEntry("link.txt", "symlink", st.st_size, st.st_mtime_ns, link, str(target))

    result_new = classify(scanned, existing=None)
    assert result_new.classification == Classification.NEW

    existing_same = FileRow(
        path="link.txt",
        kind="symlink",
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        reference_sha256=None,
        reference_size=None,
        reference_mtime_ns=None,
        hashed_at=None,
        last_seen_at="t",
        state="indexed",
        candidate_sha256=None,
        symlink_target=str(target),
    )
    result_unchanged = classify(scanned, existing_same)
    assert result_unchanged.classification == Classification.UNCHANGED

    existing_diff = FileRow(**{**vars(existing_same), "symlink_target": "/somewhere/else"})
    result_changed = classify(scanned, existing_diff)
    assert result_changed.classification == Classification.CHANGED_CONFLICT


# --- 2.4.2 preview renderer + has_findings -----------------------------------


def test_render_preview_and_has_findings(tmp_path):
    scanned = _write_and_scan(tmp_path, "a.txt", b"x")
    entries = [
        ClassifiedEntry("a.txt", Classification.NEW, scanned, None, "hash"),
        ClassifiedEntry("b.txt", Classification.UNCHANGED, scanned, None, None),
    ]
    text = render_preview(entries)
    assert "new: 1" in text
    assert "unchanged: 1" in text
    assert not has_findings(entries)

    entries.append(ClassifiedEntry("c.txt", Classification.CHANGED_CONFLICT, scanned, None, "h2"))
    assert has_findings(entries)


# --- 2.4.4 / 2.4.5 preview never mutates the DB ------------------------------


def test_default_preview_never_mutates_db_file(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")

    before = db_path.read_bytes()
    run_index(root, db_path, apply=False)
    after = db_path.read_bytes()
    assert before == after


def test_missing_file_preview_reports_without_mutating_db(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")
    run_index(root, db_path, apply=True)

    (root / "a.txt").unlink()
    before = db_path.read_bytes()
    result = run_index(root, db_path, apply=False)
    after = db_path.read_bytes()

    assert before == after
    missing = [e for e in result.entries if e.classification == Classification.MISSING]
    assert len(missing) == 1
    assert missing[0].relative_path == "a.txt"


# --- 2.5.1 apply-mode writer -------------------------------------------------


def test_apply_inserts_new_and_flags_conflict_without_touching_reference(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "new.txt").write_text("hello")
    (root / "changing.txt").write_text("original")

    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    original_row = get_file_row(conn, "changing.txt")
    conn.close()
    assert original_row is not None

    time.sleep(0.01)
    (root / "changing.txt").write_text("mutated content!!")

    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    updated_row = get_file_row(conn, "changing.txt")
    new_row = get_file_row(conn, "new.txt")
    conn.close()

    assert updated_row is not None
    assert updated_row.reference_sha256 == original_row.reference_sha256
    assert updated_row.state == "changed"
    assert updated_row.candidate_sha256 == hashlib.sha256(b"mutated content!!").hexdigest()

    assert new_row is not None
    assert new_row.reference_sha256 == hashlib.sha256(b"hello").hexdigest()
    assert new_row.state == "indexed"


def test_apply_marks_missing_without_clearing_reference(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    before = get_file_row(conn, "a.txt")
    conn.close()

    (root / "a.txt").unlink()
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    after = get_file_row(conn, "a.txt")
    conn.close()

    assert after is not None
    assert after.state == "missing"
    assert after.reference_sha256 == before.reference_sha256


# --- 2.5.2 --rehash -----------------------------------------------------------


def test_rehash_detects_corruption_with_unchanged_metadata(tmp_path):
    import os

    root, db_path = _make_storage(tmp_path)
    path = root / "a.txt"
    path.write_text("original")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    before = get_file_row(conn, "a.txt")
    conn.close()
    assert before is not None

    corrupted = b"corrupted!"[: before.size].ljust(before.size, b"\x00")
    path.write_bytes(corrupted)
    os.utime(path, ns=(before.mtime_ns, before.mtime_ns))

    result_default = run_index(root, db_path, apply=False)
    unchanged = next(e for e in result_default.entries if e.relative_path == "a.txt")
    assert unchanged.classification == Classification.UNCHANGED

    result_rehash = run_index(root, db_path, rehash=True, apply=True)
    conflict = next(e for e in result_rehash.entries if e.relative_path == "a.txt")
    assert conflict.classification == Classification.CHANGED_CONFLICT

    conn = connect(db_path)
    after = get_file_row(conn, "a.txt")
    conn.close()
    assert after is not None
    assert after.reference_sha256 == before.reference_sha256
    assert after.candidate_sha256 == conflict.computed_hash


# --- 2.5.3 incremental skip fast path ----------------------------------------


def test_unchanged_files_are_never_hashed_by_default(tmp_path, monkeypatch):
    import sbesm.indexing as indexing_mod

    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")
    run_index(root, db_path, apply=True)

    calls = {"n": 0}
    original = indexing_mod.hash_file_stable

    def spy(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(indexing_mod, "hash_file_stable", spy)
    run_index(root, db_path, apply=False)
    assert calls["n"] == 0


# --- 2.5.4 run logging --------------------------------------------------------


def test_run_log_created_and_labeled_correctly(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")

    preview_result = run_index(root, db_path, apply=False)
    assert preview_result.log_path.exists()
    assert "DRY RUN" in preview_result.log_path.read_text()

    apply_result = run_index(root, db_path, apply=True)
    assert apply_result.log_path.exists()
    assert "APPLY" in apply_result.log_path.read_text()
    assert apply_result.log_path != preview_result.log_path


# --- 2.5.5 interrupted-apply safety ------------------------------------------


def test_apply_failure_rolls_back_and_marks_run_failed(tmp_path, monkeypatch):
    import sbesm.indexing as indexing_mod

    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")

    def boom(conn, results):
        raise RuntimeError("simulated failure mid-apply")

    monkeypatch.setattr(indexing_mod, "_apply_classified_entries", boom)

    with pytest.raises(RuntimeError):
        run_index(root, db_path, apply=True)

    conn = connect(db_path)
    row = get_file_row(conn, "a.txt")
    last_run = conn.execute("SELECT outcome FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    assert row is None
    assert last_run[0] == "failed"


def test_apply_keyboard_interrupt_marks_run_interrupted(tmp_path, monkeypatch):
    import sbesm.indexing as indexing_mod

    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")

    def interrupt(conn, results):
        raise KeyboardInterrupt

    monkeypatch.setattr(indexing_mod, "_apply_classified_entries", interrupt)

    with pytest.raises(KeyboardInterrupt):
        run_index(root, db_path, apply=True)

    conn = connect(db_path)
    last_run = conn.execute("SELECT outcome FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert last_run[0] == "interrupted"
