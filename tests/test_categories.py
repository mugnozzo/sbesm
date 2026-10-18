import pytest

from sbesm.categories import discover_categories, resolve_other, validate_profiles
from sbesm.config import StorageConfig
from sbesm.errors import UsageError


def _make_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "documents").mkdir()
    (root / "photos").mkdir()
    (root / "projects").mkdir()
    (root / ".sbesm").mkdir()
    (root / "loose_file.txt").write_text("x")
    return root


def test_discover_categories_excludes_sbesm_and_files(tmp_path):
    root = _make_root(tmp_path)
    assert discover_categories(root) == ["documents", "photos", "projects"]


def test_resolve_other_returns_unlisted_dirs_and_loose_files(tmp_path):
    root = _make_root(tmp_path)
    other = resolve_other(root, known=["documents", "photos"])
    assert other == ["loose_file.txt", "projects"]


def test_resolve_other_excludes_sbesm(tmp_path):
    root = _make_root(tmp_path)
    other = resolve_other(root, known=["documents", "photos", "projects"])
    assert ".sbesm" not in other
    assert other == ["loose_file.txt"]


def test_validate_profiles_accepts_known_categories_and_other():
    config = StorageConfig(
        id="x",
        name="x",
        known_categories=["documents", "photos"],
        profiles={"work": ["documents"], "misc": ["other"]},
    )
    validate_profiles(config)  # should not raise


def test_validate_profiles_rejects_unknown_category():
    config = StorageConfig(
        id="x",
        name="x",
        known_categories=["documents"],
        profiles={"work": ["videos"]},
    )
    with pytest.raises(UsageError):
        validate_profiles(config)
