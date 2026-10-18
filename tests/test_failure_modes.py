"""Phase 7.2: removable disk and failure-mode testing."""

import shutil

import pytest

from sbesm import cli, exitcodes
from sbesm.accept_cmd import cmd_accept
from sbesm.db import storage_write_lock
from sbesm.errors import IOFailureError, StorageNotFoundError, UsageError
from sbesm.indexing import run_index
from sbesm.init_cmd import cmd_init
from sbesm.registry import classify_registry, load_registry
from sbesm.resolve import resolve_storage


def _make_storage(tmp_path, name):
    root = tmp_path / name
    cmd_init(root, name=name)
    return root


# --- missing mount ------------------------------------------------------------


def test_missing_root_directory_fails_cleanly(tmp_path):
    root = tmp_path / "ghost"
    cmd_init(root, name="ghost")
    shutil.rmtree(root)  # the whole storage, .sbesm included, vanishes

    with pytest.raises(StorageNotFoundError):
        resolve_storage(str(root))


# --- duplicate/cloned storage IDs --------------------------------------------


def test_cloned_storage_ids_flagged_ambiguous(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    original = _make_storage(tmp_path, "disk1")
    clone = tmp_path / "disk1_clone"
    shutil.copytree(original, clone)  # same storage_id baked into .sbesm

    cli.main(["register", str(original), "--name", "disk1"])
    cli.main(["register", str(clone), "--name", "disk1_clone"])

    registry_path = tmp_path / ".config" / "sbesm" / "registry.toml"
    entries = load_registry(registry_path)
    availability = classify_registry(entries)

    assert availability["disk1"] == "ambiguous"
    assert availability["disk1_clone"] == "ambiguous"


# --- read-only media -----------------------------------------------------------


def test_rsync_failure_surfaces_as_io_failure_not_silent_success(tmp_path, monkeypatch, capsys):
    # A real read-only *mount* would make this fail at the OS level, but
    # rsync -a (which includes -p, permissions) will happily chmod an
    # owned-but-555 directory back to writable before writing into it --
    # that's correct rsync behavior, not a bug, so file-permission bits
    # alone can't simulate read-only media here without real root-level
    # mount privileges. Simulate the failure at the subprocess boundary
    # instead, and confirm it's surfaced as IO_FAILURE rather than swallowed.
    import sbesm.sync as sync_mod

    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("hello")

    class FakeProc:
        returncode = 23
        stdout = "rsync: [receiver] mkstemp failed: Read-only file system (30)"

    monkeypatch.setattr(sync_mod.subprocess, "run", lambda *a, **k: FakeProc())

    code = cli.main(["sync", str(source), str(dest), "--all", "--apply"])
    capsys.readouterr()
    assert code == exitcodes.IO_FAILURE


def test_readonly_index_db_directory_refuses_apply_cleanly(tmp_path):
    root = _make_storage(tmp_path, "root")
    (root / "a.txt").write_text("hello")
    sbesm_dir = root / ".sbesm"
    sbesm_dir.chmod(0o555)  # can't write a new .lock file or WAL files here
    try:
        with pytest.raises(IOFailureError):
            run_index(root, sbesm_dir / "index.sqlite", apply=True)
    finally:
        sbesm_dir.chmod(0o755)


# --- low disk space (simulated) ----------------------------------------------


def test_simulated_disk_full_during_apply_rolls_back_cleanly(tmp_path, monkeypatch):
    import sbesm.indexing as indexing_mod

    root = _make_storage(tmp_path, "root")
    (root / "a.txt").write_text("hello")

    def boom(conn, results):
        raise OSError(28, "No space left on device")  # ENOSPC

    monkeypatch.setattr(indexing_mod, "_apply_classified_entries", boom)

    with pytest.raises(OSError):
        run_index(root, root / ".sbesm" / "index.sqlite", apply=True)

    from sbesm.db import connect

    conn = connect(root / ".sbesm" / "index.sqlite")
    last_run = conn.execute("SELECT outcome FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    files_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()

    assert last_run[0] == "failed"
    assert files_count == 0  # nothing partially committed


# --- interrupted rsync ---------------------------------------------------------


def test_sync_keyboard_interrupt_writes_interrupted_log_and_reraises(tmp_path, monkeypatch):
    import sbesm.sync as sync_mod

    source = _make_storage(tmp_path, "source")
    dest = _make_storage(tmp_path, "dest")
    (source / "a.txt").write_text("hello")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_mod.subprocess, "run", interrupt)

    with pytest.raises(KeyboardInterrupt):
        sync_mod.run_sync(source, dest, None, apply=True)

    log_dir = dest / ".sbesm" / "logs"
    logs = sorted(log_dir.glob("sync-*.log"))
    assert logs
    assert "INTERRUPTED" in logs[-1].read_text()


# --- DB locks: concurrent writers ---------------------------------------------


def test_concurrent_apply_is_refused_while_another_write_holds_the_lock(tmp_path):
    root = _make_storage(tmp_path, "root")
    (root / "a.txt").write_text("hello")

    with storage_write_lock(root / ".sbesm"), pytest.raises(IOFailureError):
        run_index(root, root / ".sbesm" / "index.sqlite", apply=True)


def test_concurrent_accept_apply_is_refused_while_locked(tmp_path):
    root = _make_storage(tmp_path, "root")
    (root / "a.txt").write_text("hello")
    run_index(root, root / ".sbesm" / "index.sqlite", apply=True)
    (root / "a.txt").write_text("changed")

    with storage_write_lock(root / ".sbesm"), pytest.raises((IOFailureError, UsageError)):
        cmd_accept(root, root / ".sbesm" / "index.sqlite", "a.txt", apply=True)


def test_concurrent_read_is_not_blocked_by_write_lock(tmp_path):
    root = _make_storage(tmp_path, "root")
    (root / "a.txt").write_text("hello")
    run_index(root, root / ".sbesm" / "index.sqlite", apply=True)

    # a plain preview (no --apply) never takes the write lock, so it must
    # succeed even while another write lock is held.
    with storage_write_lock(root / ".sbesm"):
        result = run_index(root, root / ".sbesm" / "index.sqlite", apply=False)
    assert result is not None
