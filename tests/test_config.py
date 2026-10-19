from sbesm.config import StorageConfig, read_storage_config, write_storage_config


def test_round_trip_preserves_all_fields(tmp_path):
    original = StorageConfig(
        id="11111111-1111-1111-1111-111111111111",
        name="backup1",
        filesystem_uuid="22222222-2222-2222-2222-222222222222",
        known_categories=["documents", "photos"],
        profiles={"work": ["documents"], "media": ["photos"]},
        preserve_partial=True,
        delete_by_default=False,
        hashing_algorithm="sha256",
    )
    path = tmp_path / "config.toml"

    write_storage_config(path, original)
    loaded = read_storage_config(path)

    assert loaded == original


def test_round_trip_preserves_explicit_mtime_tolerance_override(tmp_path):
    original = StorageConfig(id="x", name="x", mtime_tolerance_ns=3_000_000)
    path = tmp_path / "config.toml"

    write_storage_config(path, original)
    loaded = read_storage_config(path)

    assert loaded.mtime_tolerance_ns == 3_000_000


def test_mtime_tolerance_defaults_to_none_when_unset(tmp_path):
    original = StorageConfig(id="x", name="x")
    path = tmp_path / "config.toml"

    write_storage_config(path, original)
    loaded = read_storage_config(path)

    assert loaded.mtime_tolerance_ns is None


def test_round_trip_preserves_exclude_patterns(tmp_path):
    original = StorageConfig(id="x", name="x", exclude_patterns=[".venv", "*.pyc"])
    path = tmp_path / "config.toml"

    write_storage_config(path, original)
    loaded = read_storage_config(path)

    assert loaded.exclude_patterns == [".venv", "*.pyc"]


def test_exclude_patterns_default_to_empty_when_unset(tmp_path):
    original = StorageConfig(id="x", name="x")
    path = tmp_path / "config.toml"

    write_storage_config(path, original)
    loaded = read_storage_config(path)

    assert loaded.exclude_patterns == []
