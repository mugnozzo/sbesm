import pytest

from sbesm import cli
from sbesm.errors import StorageNotFoundError
from sbesm.registry import (
    RegistryEntry,
    classify_registry,
    find_entries_by_root,
    find_entry_by_name_or_root,
    load_registry,
    remove_entry,
    save_registry,
    upsert_entry,
)

# --- 1.4.2 registry schema + TOML I/O ---------------------------------------


def test_load_registry_on_missing_file_returns_empty(tmp_path):
    assert load_registry(tmp_path / "registry.toml") == {}


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "registry.toml"
    entry = RegistryEntry(
        name="backup1",
        storage_id="abc-123",
        last_known_root="/mnt/backup",
        filesystem_uuid="UUID-1",
        last_seen_at="2026-01-01T00:00:00+00:00",
    )
    save_registry(path, {"backup1": entry})
    loaded = load_registry(path)
    assert loaded == {"backup1": entry}


def test_upsert_updates_in_place_without_duplicating(tmp_path):
    path = tmp_path / "registry.toml"
    first = RegistryEntry("backup1", "id-1", "/mnt/a", "UUID-1", "t1")
    upsert_entry(path, first)

    second = RegistryEntry("backup1", "id-1", "/mnt/b", "UUID-1", "t2")
    upsert_entry(path, second)

    entries = load_registry(path)
    assert len(entries) == 1
    assert entries["backup1"].last_known_root == "/mnt/b"


# --- 1.4.5 availability classification ---------------------------------------


def test_classify_registry_available_and_unavailable(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    entries = {
        "live_storage": RegistryEntry("live_storage", "id-1", str(live), None, "t"),
        "dead_storage": RegistryEntry(
            "dead_storage", "id-2", str(tmp_path / "missing"), None, "t"
        ),
    }
    result = classify_registry(entries)
    assert result["live_storage"] == "available"
    assert result["dead_storage"] == "unavailable"


def test_classify_registry_detects_ambiguous_clones(tmp_path):
    root_a = tmp_path / "a"
    root_a.mkdir()
    root_b = tmp_path / "b"
    root_b.mkdir()
    entries = {
        "clone_a": RegistryEntry("clone_a", "shared-id", str(root_a), None, "t"),
        "clone_b": RegistryEntry("clone_b", "shared-id", str(root_b), None, "t"),
    }
    result = classify_registry(entries)
    assert result["clone_a"] == "ambiguous"
    assert result["clone_b"] == "ambiguous"


# --- 1.4.7 end-to-end: init -> register -> storages, against a tmp $HOME ----


def test_register_and_storages_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    root = tmp_path / "storage1"
    assert cli.main(["init", str(root), "--name", "disk1"]) == 0
    assert cli.main(["register", str(root), "--name", "disk1"]) == 0

    registry_path = tmp_path / ".config" / "sbesm" / "registry.toml"
    entries = load_registry(registry_path)
    assert "disk1" in entries
    assert entries["disk1"].last_known_root == str(root.resolve())

    assert cli.main(["storages"]) == 0


def test_register_twice_updates_existing_entry(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    root = tmp_path / "storage1"
    cli.main(["init", str(root), "--name", "disk1"])
    cli.main(["register", str(root), "--name", "disk1"])
    cli.main(["register", str(root), "--name", "disk1"])

    registry_path = tmp_path / ".config" / "sbesm" / "registry.toml"
    entries = load_registry(registry_path)
    assert len(entries) == 1


# --- find_entry_by_name_or_root / remove_entry / find_entries_by_root ------


def test_find_entry_by_exact_name(tmp_path):
    entry = RegistryEntry("disk1", "id-1", str(tmp_path / "root"), None, "t")
    entries = {"disk1": entry}
    assert find_entry_by_name_or_root(entries, "disk1") == entry


def test_find_entry_by_matching_root_path(tmp_path):
    root = tmp_path / "root"
    entry = RegistryEntry("disk1", "id-1", str(root), None, "t")
    entries = {"disk1": entry}
    assert find_entry_by_name_or_root(entries, str(root)) == entry


def test_find_entry_raises_when_not_found(tmp_path):
    with pytest.raises(StorageNotFoundError):
        find_entry_by_name_or_root({}, "nonexistent")


def test_remove_entry_deletes_and_is_idempotent(tmp_path):
    path = tmp_path / "registry.toml"
    entry = RegistryEntry("disk1", "id-1", str(tmp_path / "root"), None, "t")
    save_registry(path, {"disk1": entry})

    remove_entry(path, "disk1")
    assert load_registry(path) == {}

    remove_entry(path, "disk1")  # second call is a no-op, not an error
    assert load_registry(path) == {}


def test_find_entries_by_root_matches_resolved_path(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    entry = RegistryEntry("disk1", "id-1", str(root.resolve()), None, "t")
    other = RegistryEntry("disk2", "id-2", str(tmp_path / "elsewhere"), None, "t")
    entries = {"disk1": entry, "disk2": other}

    assert find_entries_by_root(entries, root) == [entry]
