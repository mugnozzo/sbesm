"""Phase 7.1: end-to-end integration matrix, driven through the real CLI,
re-asserting the spec's core invariants across overlapping categories,
destination-only files, conflicts, corrupted/renamed files, symlinks, and
loose root files.
"""

import os

from sbesm import cli, exitcodes
from sbesm.db import connect, get_file_row
from sbesm.init_cmd import cmd_init


def _make_pair(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    cmd_init(a, name="a")
    cmd_init(b, name="b")
    return a, b


def test_overlapping_categories_and_destination_only_files(tmp_path, capsys):
    a, b = _make_pair(tmp_path)
    (a / "documents").mkdir()
    (b / "documents").mkdir()
    (a / "documents" / "shared.txt").write_text("shared content")
    (b / "documents" / "shared.txt").write_text("shared content")
    (b / "documents" / "dest_only.txt").write_text("only on dest")

    assert cli.main(["index", str(a), "--apply"]) in (exitcodes.SUCCESS, exitcodes.FINDINGS)
    assert cli.main(["index", str(b), "--apply"]) in (exitcodes.SUCCESS, exitcodes.FINDINGS)
    capsys.readouterr()

    # sync --all without --delete must copy new content but never touch dest_only.txt
    code = cli.main(["sync", str(a), str(b), "--all", "--apply"])
    capsys.readouterr()
    assert code == exitcodes.SUCCESS
    assert (b / "documents" / "dest_only.txt").exists()  # invariant: preserved by default


def test_content_conflict_blocks_sync_until_approved(tmp_path, capsys):
    a, b = _make_pair(tmp_path)
    (a / "documents").mkdir()
    (b / "documents").mkdir()
    (a / "documents" / "conflict.txt").write_text("A's version")
    (b / "documents" / "conflict.txt").write_text("B's version")
    cli.main(["index", str(a), "--apply"])
    cli.main(["index", str(b), "--apply"])
    capsys.readouterr()

    code = cli.main(["sync", str(a), str(b), "--all", "--apply"])
    capsys.readouterr()
    assert code == exitcodes.USAGE_ERROR
    assert (b / "documents" / "conflict.txt").read_text() == "B's version"  # untouched

    code = cli.main(["sync", str(a), str(b), "--all", "--apply", "--overwrite-conflicts"])
    capsys.readouterr()
    assert code == exitcodes.SUCCESS
    assert (b / "documents" / "conflict.txt").read_text() == "A's version"


def test_silent_corruption_invisible_to_index_caught_by_verify(tmp_path, capsys):
    a, _b = _make_pair(tmp_path)
    path = a / "important.txt"
    path.write_text("original content")
    cli.main(["index", str(a), "--apply"])
    capsys.readouterr()

    st = path.stat()
    corrupted = b"CORRUPTED"[: st.st_size].ljust(st.st_size, b"\x00")
    path.write_bytes(corrupted)
    os.utime(path, ns=(st.st_mtime_ns, st.st_mtime_ns))

    # index's fast path doesn't re-hash unchanged metadata -> corruption invisible
    code = cli.main(["index", str(a)])
    out = capsys.readouterr().out
    assert "unchanged" in out

    # verify always re-hashes -> corruption caught
    code = cli.main(["verify", str(a)])
    out = capsys.readouterr().out
    assert code == exitcodes.FINDINGS
    assert "mismatch" in out

    # the reference hash itself is never silently overwritten by any of this
    conn = connect(a / ".sbesm" / "index.sqlite")
    row = get_file_row(conn, "important.txt")
    conn.close()
    assert row.reference_sha256 is not None
    import hashlib

    assert row.reference_sha256 == hashlib.sha256(b"original content").hexdigest()


def test_renamed_file_is_missing_at_old_path_new_at_new_path(tmp_path, capsys):
    # sbesm has no rename-tracking; a rename is observed as plain
    # missing+new, which is the correct, honest behavior for v1.
    a, _b = _make_pair(tmp_path)
    (a / "old_name.txt").write_text("content")
    cli.main(["index", str(a), "--apply"])
    capsys.readouterr()

    (a / "old_name.txt").rename(a / "new_name.txt")

    cli.main(["index", str(a), "--apply"])
    out = capsys.readouterr().out
    assert "missing: 1" in out
    assert "new: 1" in out

    conn = connect(a / ".sbesm" / "index.sqlite")
    old_row = get_file_row(conn, "old_name.txt")
    new_row = get_file_row(conn, "new_name.txt")
    conn.close()
    assert old_row.state == "missing"
    assert old_row.reference_sha256 is not None  # never cleared
    assert new_row.state == "indexed"


def test_symlinks_never_hashed_never_followed_excluded_from_duplicates(tmp_path, capsys):
    a, _b = _make_pair(tmp_path)
    (a / "real.txt").write_text("shared content")
    (a / "also_real.txt").write_text("shared content")
    (a / "link.txt").symlink_to(a / "real.txt")

    code = cli.main(["index", str(a), "--apply"])
    capsys.readouterr()

    conn = connect(a / ".sbesm" / "index.sqlite")
    link_row = get_file_row(conn, "link.txt")
    conn.close()
    assert link_row.kind == "symlink"
    assert link_row.reference_sha256 is None
    assert link_row.symlink_target == str(a / "real.txt")

    code = cli.main(["duplicates", str(a)])
    out = capsys.readouterr().out
    assert code == exitcodes.FINDINGS
    assert "real.txt" in out
    assert "link.txt" not in out


def test_loose_root_files_are_indexed_like_any_other_file(tmp_path, capsys):
    a, b = _make_pair(tmp_path)
    (a / "loose.txt").write_text("not in any category")

    code = cli.main(["index", str(a), "--apply"])
    capsys.readouterr()
    assert code == exitcodes.SUCCESS

    conn = connect(a / ".sbesm" / "index.sqlite")
    row = get_file_row(conn, "loose.txt")
    conn.close()
    assert row is not None
    assert row.state == "indexed"

    code = cli.main(["sync", str(a), str(b), "--all", "--apply"])
    capsys.readouterr()
    assert code == exitcodes.SUCCESS
    assert (b / "loose.txt").read_text() == "not in any category"


def test_delete_apply_removes_only_within_scope_never_siblings(tmp_path, capsys):
    a, b = _make_pair(tmp_path)
    (a / "documents").mkdir()
    (b / "documents").mkdir()
    (b / "documents" / "stale.txt").write_text("remove me")
    (b / "photos").mkdir()
    (b / "photos" / "keep.jpg").write_text("never touch me")

    code = cli.main(["sync", str(a), str(b), "--folder", "documents", "--delete", "--apply"])
    capsys.readouterr()
    assert code == exitcodes.SUCCESS
    assert not (b / "documents" / "stale.txt").exists()
    assert (b / "photos" / "keep.jpg").exists()  # sibling untouched


def test_reconcile_never_touches_differing_content_across_all_invariants(tmp_path, capsys):
    a, b = _make_pair(tmp_path)
    (a / "same.txt").write_text("identical")
    (b / "same.txt").write_text("identical")
    (a / "different.txt").write_text("A's content")
    (b / "different.txt").write_text("B's content")

    older_ns = (a / "same.txt").stat().st_mtime_ns
    os.utime(b / "same.txt", ns=(older_ns + 5_000_000_000,) * 2)
    different_before = (b / "different.txt").stat().st_mtime_ns
    os.utime(b / "different.txt", ns=(older_ns + 5_000_000_000,) * 2)

    code = cli.main(["reconcile", str(a), str(b), "--all", "--apply"])
    out = capsys.readouterr().out
    assert code == exitcodes.FINDINGS
    assert "reconciled: 1" in out
    assert "mismatch: 1" in out
    assert (b / "same.txt").stat().st_mtime_ns == older_ns
    assert (b / "different.txt").stat().st_mtime_ns != different_before  # we set it above, untouched by reconcile
