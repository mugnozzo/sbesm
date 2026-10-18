import pytest

from sbesm.config import StorageConfig
from sbesm.errors import UsageError
from sbesm.profiles import load_local_profiles, resolve_profile, save_local_profiles


def test_load_local_profiles_on_missing_file_returns_empty(tmp_path):
    assert load_local_profiles(tmp_path / "profiles.toml") == {}


def test_save_and_load_local_profiles_round_trip(tmp_path):
    path = tmp_path / "profiles.toml"
    save_local_profiles(path, {"work": ["documents", "projects"]})
    assert load_local_profiles(path) == {"work": ["documents", "projects"]}


def test_resolve_profile_prefers_local_over_storage():
    storage_config = StorageConfig(
        id="x", name="x", profiles={"work": ["documents"]}
    )
    local_profiles = {"work": ["projects"]}
    assert resolve_profile("work", storage_config, local_profiles) == ["projects"]


def test_resolve_profile_falls_back_to_storage_when_absent_locally():
    storage_config = StorageConfig(
        id="x", name="x", profiles={"work": ["documents"]}
    )
    assert resolve_profile("work", storage_config, local_profiles={}) == ["documents"]


def test_resolve_profile_raises_when_undefined_anywhere():
    storage_config = StorageConfig(id="x", name="x", profiles={})
    with pytest.raises(UsageError):
        resolve_profile("missing", storage_config, local_profiles={})
