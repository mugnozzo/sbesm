import pytest

from sbesm.defaults import save_local_default_excludes
from sbesm.errors import UsageError
from sbesm.init_cmd import cmd_init


def test_init_creates_config_and_marker(tmp_path):
    root = tmp_path / "storage1"
    config = cmd_init(root, name="backup1")

    assert (root / ".sbesm" / "config.toml").exists()
    assert (root / ".sbesm" / "storage_id").read_text() == config.id
    assert (root / ".sbesm" / "logs").is_dir()
    assert (root / ".sbesm" / "index.sqlite").exists()
    assert config.name == "backup1"


def test_second_init_is_refused_and_leaves_first_untouched(tmp_path):
    root = tmp_path / "storage1"
    cmd_init(root, name="backup1")

    config_path = root / ".sbesm" / "config.toml"
    marker_path = root / ".sbesm" / "storage_id"
    config_before = config_path.read_bytes()
    marker_before = marker_path.read_bytes()

    with pytest.raises(UsageError):
        cmd_init(root, name="backup1-again")

    assert config_path.read_bytes() == config_before
    assert marker_path.read_bytes() == marker_before


def test_init_defaults_name_to_root_dirname(tmp_path):
    root = tmp_path / "my_storage"
    config = cmd_init(root)
    assert config.name == "my_storage"


def test_init_seeds_exclude_patterns_from_local_defaults(tmp_path):
    defaults_path = tmp_path / "defaults.toml"
    save_local_default_excludes(defaults_path, [".venv", "__pycache__"])

    root = tmp_path / "storage1"
    config = cmd_init(root, name="backup1", defaults_path=defaults_path)

    assert config.exclude_patterns == [".venv", "__pycache__"]


def test_init_without_local_defaults_file_leaves_excludes_empty(tmp_path):
    root = tmp_path / "storage1"
    config = cmd_init(root, name="backup1", defaults_path=tmp_path / "no_such_defaults.toml")

    assert config.exclude_patterns == []


def test_editing_local_defaults_after_init_does_not_affect_existing_storage(tmp_path):
    defaults_path = tmp_path / "defaults.toml"
    save_local_default_excludes(defaults_path, [".venv"])

    root = tmp_path / "storage1"
    cmd_init(root, name="backup1", defaults_path=defaults_path)

    save_local_default_excludes(defaults_path, [".venv", "node_modules"])

    from sbesm.config import read_storage_config

    reloaded = read_storage_config(root / ".sbesm" / "config.toml")
    assert reloaded.exclude_patterns == [".venv"]


def test_init_records_detected_filesystem_uuid(tmp_path, monkeypatch):
    from sbesm import init_cmd

    monkeypatch.setattr(init_cmd, "detect_filesystem_uuid", lambda *a, **k: "MOCK-UUID")
    monkeypatch.setattr(init_cmd, "is_mounted_and_responsive", lambda *a, **k: True)

    root = tmp_path / "storage1"
    config = cmd_init(root, name="backup1")

    assert config.filesystem_uuid == "MOCK-UUID"
