import hashlib
import os

from sbesm.db import connect
from sbesm.indexing import run_index
from sbesm.migrations import MIGRATIONS, apply_migrations
from sbesm.verify import (
    VerifiedEntry,
    VerifyStatus,
    has_verify_findings,
    render_verify_summary,
    run_verify,
)


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


# --- 3.1 verify engine: full taxonomy ---------------------------------------


def test_verify_reports_ok_for_untouched_file(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")
    run_index(root, db_path, apply=True)

    result = run_verify(root, db_path)
    entry = next(e for e in result.entries if e.relative_path == "a.txt")
    assert entry.status == VerifyStatus.OK
    assert not has_verify_findings([entry])


def test_render_verify_summary_lists_all_anomalies_no_truncation():
    entries = [
        VerifiedEntry(f"bad{i}.txt", VerifyStatus.MISMATCH) for i in range(15)
    ]
    text = render_verify_summary(entries)
    for i in range(15):
        assert f"bad{i}.txt" in text


def test_verify_catches_mismatch_even_with_restored_metadata(tmp_path):
    root, db_path = _make_storage(tmp_path)
    path = root / "a.txt"
    path.write_text("original")
    run_index(root, db_path, apply=True)

    st_before = path.stat()
    # corrupt content but restore size/mtime so index's fast path would miss it
    corrupted = b"corrupted"[: st_before.st_size].ljust(st_before.st_size, b"\x00")
    path.write_bytes(corrupted)
    os.utime(path, ns=(st_before.st_mtime_ns, st_before.st_mtime_ns))

    result = run_verify(root, db_path)
    entry = next(e for e in result.entries if e.relative_path == "a.txt")
    assert entry.status == VerifyStatus.MISMATCH
    assert entry.fresh_hash == hashlib.sha256(corrupted).hexdigest()


def test_verify_reports_missing(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")
    run_index(root, db_path, apply=True)
    (root / "a.txt").unlink()

    result = run_verify(root, db_path)
    entry = next(e for e in result.entries if e.relative_path == "a.txt")
    assert entry.status == VerifyStatus.MISSING


def test_verify_reports_unindexed_for_file_never_indexed(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "never_indexed.txt").write_text("x")

    result = run_verify(root, db_path)
    entry = next(e for e in result.entries if e.relative_path == "never_indexed.txt")
    assert entry.status == VerifyStatus.UNINDEXED


def test_verify_reports_symlink_status_separately(tmp_path):
    root, db_path = _make_storage(tmp_path)
    target = root / "real.txt"
    target.write_text("x")
    link = root / "link.txt"
    link.symlink_to(target)

    result = run_verify(root, db_path)
    entry = next(e for e in result.entries if e.relative_path == "link.txt")
    assert entry.status == VerifyStatus.SYMLINK
    assert not has_verify_findings([entry])


def test_verify_never_writes_reference_hash(tmp_path):
    root, db_path = _make_storage(tmp_path)
    path = root / "a.txt"
    path.write_text("original")
    run_index(root, db_path, apply=True)

    st_before = path.stat()
    corrupted = b"corrupted"[: st_before.st_size].ljust(st_before.st_size, b"\x00")
    path.write_bytes(corrupted)
    os.utime(path, ns=(st_before.st_mtime_ns, st_before.st_mtime_ns))

    from sbesm.db import get_file_row

    conn = connect(db_path)
    before_row = get_file_row(conn, "a.txt")
    conn.close()

    run_verify(root, db_path)

    conn = connect(db_path)
    after_row = get_file_row(conn, "a.txt")
    conn.close()

    assert after_row.reference_sha256 == before_row.reference_sha256


def test_verify_run_recorded_in_runs_table(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("x")
    run_index(root, db_path, apply=True)

    run_verify(root, db_path)

    conn = connect(db_path)
    row = conn.execute(
        "SELECT outcome FROM runs WHERE command = 'verify' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == "success"
