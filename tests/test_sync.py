import hashlib

import pytest

from sbesm.db import connect, get_file_row
from sbesm.errors import StorageUnavailableError, UsageError
from sbesm.indexing import run_index
from sbesm.init_cmd import cmd_init
from sbesm.sync import build_rsync_command, run_sync


def _make_storage(tmp_path, name):
    root = tmp_path / name
    cmd_init(root, name=name)
    return root


# --- 5.1 safe rsync command builder ------------------------------------------


def test_build_rsync_command_directory_uses_trailing_slashes(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dst"
    cmd = build_rsync_command(source, dest, dry_run=True)
    assert cmd[0] == "rsync"
    assert "-a" in cmd
    assert "--itemize-changes" in cmd
    assert "--partial-dir=.rsync-partial" in cmd
    assert "--exclude=/.sbesm/" in cmd
    assert "--dry-run" in cmd
    assert cmd[-2] == f"{source}/"
    assert cmd[-1] == f"{dest}/"


def test_build_rsync_command_file_has_no_trailing_slash(tmp_path):
    source = tmp_path / "src.txt"
    source.write_text("x")
    dest = tmp_path / "dst.txt"
    cmd = build_rsync_command(source, dest, dry_run=True)
    assert cmd[-2] == str(source)
    assert cmd[-1] == str(dest)


def test_build_rsync_command_update_and_delete_flags(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dst"
    cmd = build_rsync_command(source, dest, dry_run=False, delete=True, update=True)
    assert "--update" in cmd
    assert "--delete" in cmd
    assert "--dry-run" not in cmd


# --- 5.2 dry-run sync never changes either storage ---------------------------


def test_default_sync_is_preview_and_changes_nothing(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("hello")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)

    result = run_sync(source, dest, None)  # apply defaults to False

    assert result.applied is False
    assert not (dest / "a.txt").exists()


# --- 5.3 non-deleting --apply -------------------------------------------------


def test_apply_copies_new_files_and_preserves_dest_only(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "new_from_source.txt").write_text("hello")
    (dest / "only_on_dest.txt").write_text("keep me")

    result = run_sync(source, dest, None, apply=True)

    assert (dest / "new_from_source.txt").read_text() == "hello"
    assert (dest / "only_on_dest.txt").exists()  # preserved, no --delete
    assert any(e.relative_path == "only_on_dest.txt" for e in result.dest_only)


# --- 5.4 conflict approval + --update ----------------------------------------


def test_apply_refuses_on_content_conflict_without_overwrite_flag(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("source version")
    (dest / "a.txt").write_text("dest version")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    with pytest.raises(UsageError):
        run_sync(source, dest, None, apply=True)

    assert (dest / "a.txt").read_text() == "dest version"  # untouched


def test_apply_with_overwrite_conflicts_copies_source_version(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("source version")
    (dest / "a.txt").write_text("dest version")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    run_sync(source, dest, None, apply=True, overwrite_conflicts=True)

    assert (dest / "a.txt").read_text() == "source version"


def test_overwrite_conflicts_forces_checksum_past_coincidental_mtime_match(tmp_path):
    # regression test: rsync's default quick-check trusts size+mtime, not
    # content. Two same-size files that happen to share an mtime (seen in
    # practice on some filesystems for two independent, rapid writes) would
    # make plain `rsync -a` silently skip a real content difference. Since
    # sbesm's own conflict detection already proved these differ, approving
    # --overwrite-conflicts must still actually overwrite.
    import os

    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("source vers")  # same length as below
    (dest / "a.txt").write_text("dest versio")
    shared_ns = source.stat().st_mtime_ns
    os.utime(source / "a.txt", ns=(shared_ns, shared_ns))
    os.utime(dest / "a.txt", ns=(shared_ns, shared_ns))
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    run_sync(source, dest, None, apply=True, overwrite_conflicts=True)

    assert (dest / "a.txt").read_text() == "source vers"


def test_preview_never_requires_overwrite_conflicts(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("source version")
    (dest / "a.txt").write_text("dest version")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    result = run_sync(source, dest, None)  # preview, no --apply
    assert any(e.relative_path == "a.txt" for e in result.conflicts)
    assert (dest / "a.txt").read_text() == "dest version"  # never touched


# --- 5.5 explicit deletion ----------------------------------------------------


def test_delete_alone_is_still_preview(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (dest / "stale.txt").write_text("remove me?")

    run_sync(source, dest, None, delete=True)  # no --apply
    assert (dest / "stale.txt").exists()


def test_delete_apply_removes_destination_only_within_scope(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "documents").mkdir()
    (source / "documents" / "keep.txt").write_text("x")
    (dest / "documents").mkdir()
    (dest / "documents" / "stale.txt").write_text("remove me")

    run_sync(source, dest, ["documents"], delete=True, apply=True)

    assert not (dest / "documents" / "stale.txt").exists()
    assert (dest / "documents" / "keep.txt").exists()


def test_missing_source_selector_never_deletes_destination_counterpart(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (dest / "photos").mkdir()
    (dest / "photos" / "precious.jpg").write_text("irreplaceable")
    # source has no "photos" directory at all

    result = run_sync(source, dest, ["photos"], delete=True, apply=True)

    assert (dest / "photos" / "precious.jpg").exists()
    skipped = next(o for o in result.outcomes if o.selector == "photos")
    assert skipped.skipped_reason is not None


def test_delete_never_touches_siblings_outside_scope(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "documents").mkdir()
    (dest / "documents").mkdir()
    (dest / "photos").mkdir()
    (dest / "photos" / "untouched.jpg").write_text("x")

    run_sync(source, dest, ["documents"], delete=True, apply=True)

    assert (dest / "photos" / "untouched.jpg").exists()


# --- 5.6 post-sync indexing + interruption recovery --------------------------


def test_post_sync_reindex_refreshes_destination_hash_from_real_content(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("hello")

    run_sync(source, dest, None, apply=True)

    conn = connect(dest / ".sbesm" / "index.sqlite")
    row = get_file_row(conn, "a.txt")
    conn.close()
    assert row is not None
    assert row.reference_sha256 == hashlib.sha256(b"hello").hexdigest()


def test_root_overlap_is_rejected(tmp_path):
    source = _make_storage(tmp_path, "source")
    nested_dest = source / "nested"
    with pytest.raises(UsageError):
        run_sync(source, nested_dest, None)


def test_apply_checks_mount_liveness(tmp_path, monkeypatch):
    import sbesm.sync as sync_mod

    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("hello")

    monkeypatch.setattr(sync_mod, "is_mounted_and_responsive", lambda *a, **k: False)
    with pytest.raises(StorageUnavailableError):
        run_sync(source, dest, None, apply=True)


def test_sync_log_written_and_labeled(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("hello")

    preview_result = run_sync(source, dest, None)
    assert preview_result.log_path is not None
    assert preview_result.log_path.exists()
    assert "DRY RUN" in preview_result.log_path.read_text()

    apply_result = run_sync(source, dest, None, apply=True)
    assert apply_result.log_path is not None
    assert "APPLY" in apply_result.log_path.read_text()


def test_partial_dir_excluded_from_post_sync_index(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("hello")
    # simulate a leftover partial-transfer artifact already present on dest
    (dest / ".rsync-partial").mkdir()
    (dest / ".rsync-partial" / "leftover.tmp").write_text("junk")

    run_sync(source, dest, None, apply=True)

    conn = connect(dest / ".sbesm" / "index.sqlite")
    row = get_file_row(conn, ".rsync-partial/leftover.tmp")
    conn.close()
    assert row is None


# --- regression: Bug 1, dry-run creating destination directories ------------


def test_preview_with_nested_missing_selector_creates_nothing_on_disk(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "documents" / "archive").mkdir(parents=True)
    (source / "documents" / "archive" / "a.txt").write_text("hello")
    # dest has NO "documents" directory at all yet

    run_sync(source, dest, ["documents/archive"])  # preview, apply defaults False

    assert not (dest / "documents").exists()


def test_apply_with_nested_missing_selector_still_creates_destination_dirs(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "documents" / "archive").mkdir(parents=True)
    (source / "documents" / "archive" / "a.txt").write_text("hello")

    run_sync(source, dest, ["documents/archive"], apply=True)

    assert (dest / "documents" / "archive" / "a.txt").read_text() == "hello"


# --- regression: Bug 2, symlinked selector escaping the storage root -------


def test_symlinked_source_selector_is_rejected(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("should never be touched")
    (source / "documents").symlink_to(outside)

    with pytest.raises(UsageError):
        run_sync(source, dest, ["documents"], apply=True)

    assert not (dest / "documents").exists()


def test_symlinked_dest_selector_is_rejected(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "documents").mkdir()
    (source / "documents" / "a.txt").write_text("hello")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("should never be touched")
    (dest / "documents").symlink_to(outside)

    with pytest.raises(UsageError):
        run_sync(source, dest, ["documents"], apply=True, delete=True)

    assert (outside / "precious.txt").read_text() == "should never be touched"


def test_symlinked_selector_rejected_even_in_preview(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    outside = tmp_path / "outside"
    outside.mkdir()
    (source / "documents").symlink_to(outside)

    with pytest.raises(UsageError):
        run_sync(source, dest, ["documents"])  # preview, no --apply


def test_symlink_pointing_inside_root_is_still_allowed(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    real = source / "real_archive"
    real.mkdir()
    (real / "a.txt").write_text("hello")
    (source / "documents").symlink_to(real)

    result = run_sync(source, dest, ["documents"], apply=True)
    assert all(o.skipped_reason is None for o in result.outcomes)
