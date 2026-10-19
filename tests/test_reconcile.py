import os

import pytest

from sbesm.db import connect, get_file_row
from sbesm.errors import UsageError
from sbesm.indexing import run_index
from sbesm.init_cmd import cmd_init
from sbesm.reconcile import (
    ReconcileAction,
    ReconcileEntry,
    _apply_mtime,
    render_reconcile_summary,
    run_reconcile,
)


def _make_storage(tmp_path, name):
    root = tmp_path / name
    cmd_init(root, name=name)
    return root


def _status_for(entries, path):
    return next(e for e in entries if e.relative_path == path)


# --- 6.1 find equal-content timestamp differences ---------------------------


def test_render_reconcile_summary_lists_all_reconciled_paths_no_truncation():
    entries = [
        ReconcileEntry(f"file{i}.txt", ReconcileAction.RECONCILED) for i in range(15)
    ]
    text = render_reconcile_summary(entries)
    for i in range(15):
        assert f"file{i}.txt" in text


def test_identical_content_different_mtime_is_a_candidate(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "x.txt").write_text("same content")
    (b / "x.txt").write_text("same content")
    os.utime(b / "x.txt", ns=((a / "x.txt").stat().st_mtime_ns + 5_000_000_000,) * 2)

    result = run_reconcile(a, b, None)
    entry = _status_for(result.entries, "x.txt")
    assert entry.action == ReconcileAction.RECONCILED


def test_differing_content_is_always_skipped_never_touched(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "x.txt").write_text("content A")
    (b / "x.txt").write_text("content B")
    os.utime(b / "x.txt", ns=((a / "x.txt").stat().st_mtime_ns + 5_000_000_000,) * 2)

    before_b_mtime = (b / "x.txt").stat().st_mtime_ns
    result = run_reconcile(a, b, None, apply=True)

    entry = _status_for(result.entries, "x.txt")
    assert entry.action == ReconcileAction.SKIPPED_MISMATCH
    assert (b / "x.txt").stat().st_mtime_ns == before_b_mtime  # untouched


def test_missing_on_one_side_is_skipped(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "only_a.txt").write_text("x")

    result = run_reconcile(a, b, None)
    entry = _status_for(result.entries, "only_a.txt")
    assert entry.action == ReconcileAction.SKIPPED_MISSING


def test_symlinks_are_skipped(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    target_a = a / "real.txt"
    target_a.write_text("x")
    (a / "link.txt").symlink_to(target_a)
    target_b = b / "real.txt"
    target_b.write_text("x")
    (b / "link.txt").symlink_to(target_b)

    result = run_reconcile(a, b, None)
    entry = _status_for(result.entries, "link.txt")
    assert entry.action == ReconcileAction.SKIPPED_SYMLINK


# --- 6.2 oldest-first preview (default) --------------------------------------


def test_default_policy_is_oldest_and_preview_does_not_touch_disk(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "x.txt").write_text("same content")
    (b / "x.txt").write_text("same content")
    older_ns = (a / "x.txt").stat().st_mtime_ns
    newer_ns = older_ns + 5_000_000_000
    os.utime(b / "x.txt", ns=(newer_ns, newer_ns))

    result = run_reconcile(a, b, None)  # preview, default policy
    entry = _status_for(result.entries, "x.txt")

    assert entry.action == ReconcileAction.RECONCILED
    assert entry.target_mtime_ns == older_ns
    assert entry.updated_side == "b"
    # preview never touches disk
    assert (b / "x.txt").stat().st_mtime_ns == newer_ns


# --- 6.3 alternate policies ---------------------------------------------------


def test_newest_policy_updates_the_older_copy(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "x.txt").write_text("same content")
    (b / "x.txt").write_text("same content")
    older_ns = (a / "x.txt").stat().st_mtime_ns
    newer_ns = older_ns + 5_000_000_000
    os.utime(b / "x.txt", ns=(newer_ns, newer_ns))

    result = run_reconcile(a, b, None, policy="newest", apply=True)
    entry = _status_for(result.entries, "x.txt")

    assert entry.updated_side == "a"
    assert (a / "x.txt").stat().st_mtime_ns == newer_ns


def test_source_policy_always_makes_b_follow_a(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "x.txt").write_text("same content")
    (b / "x.txt").write_text("same content")
    a_ns = (a / "x.txt").stat().st_mtime_ns
    # make B *older* than A -- under "source", B must still follow A exactly,
    # regardless of chronological direction.
    b_ns = a_ns - 10_000_000_000
    os.utime(b / "x.txt", ns=(b_ns, b_ns))

    result = run_reconcile(a, b, None, policy="source", apply=True)
    entry = _status_for(result.entries, "x.txt")

    assert entry.updated_side == "b"
    assert (b / "x.txt").stat().st_mtime_ns == a_ns


def test_invalid_policy_rejected(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    with pytest.raises(UsageError):
        run_reconcile(a, b, None, policy="bogus")


# --- 6.4 apply + precision handling, idempotency -----------------------------


def test_apply_mtime_preserves_whatever_atime_is_current(tmp_path):
    # unit-level: confirms _apply_mtime passes through the file's current
    # atime rather than resetting it to "now" -- isolated from reconcile's
    # own content-hash read, which (on a normal relatime mount) naturally
    # advances atime as an unrelated side effect of reading the file.
    path = tmp_path / "x.txt"
    path.write_text("hello")
    st_before = path.stat()
    new_mtime_ns = st_before.st_mtime_ns + 5_000_000_000

    _apply_mtime(path, new_mtime_ns)

    st_after = path.stat()
    assert st_after.st_mtime_ns == new_mtime_ns
    assert st_after.st_atime_ns == st_before.st_atime_ns


def test_apply_sets_mtime_and_refreshes_index(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "x.txt").write_text("same content")
    (b / "x.txt").write_text("same content")
    run_index(a, a / ".sbesm" / "index.sqlite", apply=True)
    run_index(b, b / ".sbesm" / "index.sqlite", apply=True)

    older_ns = (a / "x.txt").stat().st_mtime_ns
    newer_ns = older_ns + 5_000_000_000
    os.utime(b / "x.txt", ns=(newer_ns, newer_ns))

    run_reconcile(a, b, None, apply=True)

    st = (b / "x.txt").stat()
    assert st.st_mtime_ns == older_ns

    conn = connect(b / ".sbesm" / "index.sqlite")
    row = get_file_row(conn, "x.txt")
    conn.close()
    assert row.mtime_ns == older_ns


def test_repeated_reconciliation_is_idempotent_within_tolerance(tmp_path):
    a = _make_storage(tmp_path, "a")
    b = _make_storage(tmp_path, "b")
    (a / "x.txt").write_text("same content")
    (b / "x.txt").write_text("same content")
    older_ns = (a / "x.txt").stat().st_mtime_ns
    newer_ns = older_ns + 5_000_000_000
    os.utime(b / "x.txt", ns=(newer_ns, newer_ns))

    run_reconcile(a, b, None, apply=True)
    second = run_reconcile(a, b, None, apply=True)

    entry = _status_for(second.entries, "x.txt")
    assert entry.action == ReconcileAction.ALREADY_ALIGNED
