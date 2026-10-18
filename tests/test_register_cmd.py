import pytest

from sbesm.errors import AmbiguousStorageError, UsageError
from sbesm.init_cmd import cmd_init
from sbesm.register_cmd import cmd_register
from sbesm.registry import load_registry


def test_register_requires_initialized_storage(tmp_path):
    root = tmp_path / "not_initialized"
    root.mkdir()
    with pytest.raises(UsageError):
        cmd_register(root, registry_path=tmp_path / "registry.toml")


def test_register_detects_tampered_marker(tmp_path):
    root = tmp_path / "storage1"
    cmd_init(root, name="backup1")
    (root / ".sbesm" / "storage_id").write_text("not-the-real-id")

    with pytest.raises(AmbiguousStorageError):
        cmd_register(root, registry_path=tmp_path / "registry.toml")


def test_register_name_defaults_to_config_name(tmp_path):
    root = tmp_path / "storage1"
    cmd_init(root, name="backup1")

    registry_path = tmp_path / "registry.toml"
    entry = cmd_register(root, registry_path=registry_path)

    assert entry.name == "backup1"
    assert load_registry(registry_path)["backup1"].storage_id == entry.storage_id
