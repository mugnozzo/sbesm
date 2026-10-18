from sbesm import cli, exitcodes
from sbesm.registry import load_registry


def _registry_path(tmp_path):
    return tmp_path / ".config" / "sbesm" / "registry.toml"


def _set_up_registered_storage(tmp_path, monkeypatch, name):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / name
    cli.main(["init", str(root), "--name", name])
    cli.main(["register", str(root), "--name", name])
    return root


# --- unregister ---------------------------------------------------------------


def test_unregister_declines_without_yes_leaves_entry(tmp_path, monkeypatch, capsys):
    _set_up_registered_storage(tmp_path, monkeypatch, "disk1")
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    code = cli.main(["unregister", "disk1"])
    out = capsys.readouterr().out

    assert code == exitcodes.SUCCESS
    assert "Aborted" in out
    assert "disk1" in load_registry(_registry_path(tmp_path))


def test_unregister_confirmed_removes_entry(tmp_path, monkeypatch, capsys):
    _set_up_registered_storage(tmp_path, monkeypatch, "disk1")
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    code = cli.main(["unregister", "disk1"])
    capsys.readouterr()

    assert code == exitcodes.SUCCESS
    assert "disk1" not in load_registry(_registry_path(tmp_path))


def test_unregister_yes_flag_skips_prompt(tmp_path, monkeypatch, capsys):
    _set_up_registered_storage(tmp_path, monkeypatch, "disk1")
    capsys.readouterr()

    def explode(_prompt):
        raise AssertionError("input() should not be called when --yes is passed")

    monkeypatch.setattr("builtins.input", explode)
    code = cli.main(["unregister", "disk1", "--yes"])
    capsys.readouterr()

    assert code == exitcodes.SUCCESS
    assert "disk1" not in load_registry(_registry_path(tmp_path))


def test_unregister_works_on_stale_entry_even_if_path_is_gone(tmp_path, monkeypatch, capsys):
    root = _set_up_registered_storage(tmp_path, monkeypatch, "disk1")
    import shutil

    shutil.rmtree(root)
    capsys.readouterr()

    code = cli.main(["unregister", "disk1", "--yes"])
    capsys.readouterr()

    assert code == exitcodes.SUCCESS
    assert "disk1" not in load_registry(_registry_path(tmp_path))


# --- uninit --------------------------------------------------------------------


def test_uninit_preview_without_apply_changes_nothing(tmp_path, capsys):
    root = tmp_path / "storage1"
    cli.main(["init", str(root), "--name", "storage1"])
    capsys.readouterr()

    code = cli.main(["uninit", str(root)])
    out = capsys.readouterr().out

    assert code == exitcodes.SUCCESS
    assert "Would remove" in out
    assert (root / ".sbesm").exists()


def test_uninit_apply_without_confirmation_changes_nothing(tmp_path, monkeypatch, capsys):
    root = tmp_path / "storage1"
    cli.main(["init", str(root), "--name", "storage1"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    code = cli.main(["uninit", str(root), "--apply"])
    out = capsys.readouterr().out

    assert code == exitcodes.SUCCESS
    assert "Aborted" in out
    assert (root / ".sbesm").exists()


def test_uninit_apply_confirmed_removes_sbesm_and_registry_entry(tmp_path, monkeypatch, capsys):
    root = _set_up_registered_storage(tmp_path, monkeypatch, "disk1")
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    code = cli.main(["uninit", str(root), "--apply"])
    out = capsys.readouterr().out

    assert code == exitcodes.SUCCESS
    assert not (root / ".sbesm").exists()
    assert "Also removed" in out
    assert "disk1" not in load_registry(_registry_path(tmp_path))


def test_uninit_apply_yes_flag_skips_prompt(tmp_path, capsys):
    root = tmp_path / "storage1"
    cli.main(["init", str(root), "--name", "storage1"])
    capsys.readouterr()

    code = cli.main(["uninit", str(root), "--apply", "--yes"])
    capsys.readouterr()

    assert code == exitcodes.SUCCESS
    assert not (root / ".sbesm").exists()
