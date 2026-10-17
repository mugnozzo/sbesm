import pytest

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
