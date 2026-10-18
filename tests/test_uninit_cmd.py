import pytest

from sbesm.errors import IOFailureError, UsageError
from sbesm.init_cmd import cmd_init
from sbesm.uninit_cmd import cmd_uninit


def _make_storage(tmp_path, name):
    root = tmp_path / name
    cmd_init(root, name=name)
    return root


def test_preview_never_deletes_anything(tmp_path):
    root = _make_storage(tmp_path, "storage1")
    preview = cmd_uninit(root, apply=False)

    assert preview.sbesm_dir == root / ".sbesm"
    assert preview.storage_id is not None
    assert preview.sbesm_dir.is_dir()  # still there


def test_apply_removes_sbesm_directory(tmp_path):
    root = _make_storage(tmp_path, "storage1")
    (root / "a.txt").write_text("hello")

    cmd_uninit(root, apply=True)

    assert not (root / ".sbesm").exists()
    assert (root / "a.txt").exists()  # user files untouched


def test_log_file_count_reflects_prior_runs(tmp_path):
    from sbesm.indexing import run_index

    root = _make_storage(tmp_path, "storage1")
    (root / "a.txt").write_text("hello")
    run_index(root, root / ".sbesm" / "index.sqlite", apply=True)

    preview = cmd_uninit(root, apply=False)
    assert preview.log_file_count >= 1


def test_raises_usage_error_when_not_initialized(tmp_path):
    root = tmp_path / "plain_dir"
    root.mkdir()
    with pytest.raises(UsageError):
        cmd_uninit(root, apply=False)


def test_rmtree_failure_surfaces_as_io_failure(tmp_path, monkeypatch):
    import sbesm.uninit_cmd as uninit_mod

    root = _make_storage(tmp_path, "storage1")

    def boom(path):
        raise OSError("simulated failure removing directory")

    monkeypatch.setattr(uninit_mod.shutil, "rmtree", boom)

    with pytest.raises(IOFailureError):
        cmd_uninit(root, apply=True)
