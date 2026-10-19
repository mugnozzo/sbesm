from sbesm.defaults import load_local_default_excludes, save_local_default_excludes


def test_load_on_missing_file_returns_empty(tmp_path):
    assert load_local_default_excludes(tmp_path / "defaults.toml") == []


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "defaults.toml"
    save_local_default_excludes(path, [".venv", "__pycache__"])
    assert load_local_default_excludes(path) == [".venv", "__pycache__"]
