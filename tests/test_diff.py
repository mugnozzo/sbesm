from sbesm.diff import DiffEntry, DiffStatus, has_diff_findings, render_diff_report, run_diff
from sbesm.indexing import run_index
from sbesm.init_cmd import cmd_init
from sbesm.scope import ResolvedSide


def _make_storage(tmp_path, name):
    root = tmp_path / name
    cmd_init(root, name=name)
    return root


def _status_for(entries, path):
    return next(e.status for e in entries if e.relative_path == path)


def test_render_diff_report_lists_all_conflicts_no_truncation():
    entries = [DiffEntry(f"conflict{i}.txt", DiffStatus.DIFFERENT) for i in range(15)]
    text = render_diff_report(entries)
    for i in range(15):
        assert f"conflict{i}.txt" in text


def test_render_diff_report_lists_all_dest_only_no_truncation():
    entries = [DiffEntry(f"destonly{i}.txt", DiffStatus.DEST_ONLY) for i in range(15)]
    text = render_diff_report(entries)
    for i in range(15):
        assert f"destonly{i}.txt" in text


# --- 4.2 diff by path/metadata -----------------------------------------------


def test_source_only_and_dest_only(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "only_in_source.txt").write_text("x")
    (dest / "only_in_dest.txt").write_text("y")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    entries = run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))
    assert _status_for(entries, "only_in_source.txt") == DiffStatus.SOURCE_ONLY
    assert _status_for(entries, "only_in_dest.txt") == DiffStatus.DEST_ONLY


def test_type_mismatch(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "thing").mkdir()
    (source / "thing" / "inner.txt").write_text("x")
    (dest / "thing").write_text("not a dir")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    entries = run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))
    assert _status_for(entries, "thing") == DiffStatus.TYPE_MISMATCH


def test_diff_never_writes_to_either_storage(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("same")
    (dest / "a.txt").write_text("same")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    source_db = source / ".sbesm" / "index.sqlite"
    dest_db = dest / ".sbesm" / "index.sqlite"
    before_source = source_db.read_bytes()
    before_dest = dest_db.read_bytes()

    run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))

    assert source_db.read_bytes() == before_source
    assert dest_db.read_bytes() == before_dest


# --- 4.3 checksum-aware diff, reaffirms decision #2 --------------------------


def test_equal_content_trusted_on_both_sides(tmp_path):
    import os

    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("same content")
    (dest / "a.txt").write_text("same content")
    # force identical mtimes: two independent writes essentially never land
    # on the same nanosecond-resolution timestamp by chance.
    shared_ns = source.stat().st_mtime_ns
    os.utime(source / "a.txt", ns=(shared_ns, shared_ns))
    os.utime(dest / "a.txt", ns=(shared_ns, shared_ns))
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    entries = run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))
    assert _status_for(entries, "a.txt") == DiffStatus.EQUAL


def test_different_content_flagged_as_conflict(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("source content")
    (dest / "a.txt").write_text("dest content")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    entries = run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))
    assert _status_for(entries, "a.txt") == DiffStatus.DIFFERENT
    assert has_diff_findings(entries)


def test_stale_reference_on_either_side_yields_unknown_not_equal(tmp_path):
    import os

    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("same content")
    (dest / "a.txt").write_text("same content")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    # silently corrupt dest's file while preserving metadata, so dest's stored
    # reference is now stale for its *current* content -- diff must not use it
    # to assert equality.
    path = dest / "a.txt"
    st = path.stat()
    path.write_bytes(b"corrupted content!")
    os.utime(path, ns=(st.st_mtime_ns, st.st_mtime_ns))

    entries = run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))
    assert _status_for(entries, "a.txt") == DiffStatus.UNKNOWN


def test_same_content_different_mtime(tmp_path):
    import os

    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("same content")
    (dest / "a.txt").write_text("same content")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    # bump dest's mtime without changing content, then re-index dest so its
    # reference stays trustworthy for the new (still-identical) content.
    path = dest / "a.txt"
    os.utime(path, ns=(path.stat().st_mtime_ns + 5_000_000_000,) * 2)
    run_index(dest, dest / ".sbesm" / "index.sqlite", apply=True)

    entries = run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))
    assert _status_for(entries, "a.txt") == DiffStatus.SAME_CONTENT_DIFFERENT_MTIME


# --- 4.4 conflict / destination-only reporting --------------------------------


def test_unknown_content_from_unindexed_file_is_not_falsely_equal(tmp_path):
    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("same content")
    (dest / "a.txt").write_text("same content")
    run_index(source, source / ".sbesm" / "index.sqlite", apply=True)
    # dest's copy is never indexed -> no trusted reference at all

    entries = run_diff(ResolvedSide(source, None), ResolvedSide(dest, None))
    assert _status_for(entries, "a.txt") == DiffStatus.UNKNOWN
