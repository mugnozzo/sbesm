import pytest

from sbesm.errors import StorageNotFoundError
from sbesm.registry import RegistryEntry, save_registry
from sbesm.resolve import resolve_storage


def test_resolve_by_direct_path(tmp_path):
    root = tmp_path / "storage1"
    root.mkdir()
    (root / ".sbesm").mkdir()

    resolved = resolve_storage(str(root), registry_path=tmp_path / "registry.toml")
    assert resolved == root


def test_resolve_by_registry_name(tmp_path):
    registry_path = tmp_path / "registry.toml"
    root = tmp_path / "storage1"
    entry = RegistryEntry("disk1", "id-1", str(root), None, "t")
    save_registry(registry_path, {"disk1": entry})

    resolved = resolve_storage("disk1", registry_path=registry_path)
    assert resolved == root


def test_resolve_not_found_raises(tmp_path):
    with pytest.raises(StorageNotFoundError):
        resolve_storage("nonexistent", registry_path=tmp_path / "registry.toml")
