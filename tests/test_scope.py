import pytest

from sbesm.config import StorageConfig
from sbesm.errors import UsageError
from sbesm.scope import SelectionSpec, resolve_side, validate_selection_spec


def _make_root(tmp_path, name="root"):
    root = tmp_path / name
    root.mkdir()
    (root / "documents").mkdir()
    (root / "photos").mkdir()
    (root / "stray").mkdir()  # unlisted -> part of 'other'
    (root / "loose.txt").write_text("x")  # loose root file -> part of 'other'
    return root


# --- selection spec validation -----------------------------------------------


def test_requires_exactly_one_selection_mode():
    with pytest.raises(UsageError):
        validate_selection_spec(SelectionSpec())  # none chosen
    with pytest.raises(UsageError):
        validate_selection_spec(SelectionSpec(all=True, profile="work"))  # two chosen
    validate_selection_spec(SelectionSpec(all=True))  # ok
    validate_selection_spec(SelectionSpec(folders=["documents"]))  # ok


# --- 4.1 scope resolution, decision #6 ---------------------------------------


def test_all_resolves_to_whole_root_with_no_other_echo(tmp_path):
    root = _make_root(tmp_path)
    config = StorageConfig(id="x", name="x", known_categories=["documents", "photos"])
    side = resolve_side(SelectionSpec(all=True), root, config)
    assert side.selectors is None
    assert side.other_contents is None


def test_folder_selectors_resolve_without_other(tmp_path):
    root = _make_root(tmp_path)
    config = StorageConfig(id="x", name="x", known_categories=["documents", "photos"])
    side = resolve_side(SelectionSpec(folders=["documents", "photos"]), root, config)
    assert side.selectors == ["documents", "photos"]
    assert side.other_contents is None


def test_profile_referencing_other_is_resolved_and_echoed_independently_per_side(tmp_path):
    root_a = _make_root(tmp_path, "a")
    (root_a / "a_only_stray").mkdir()
    root_b = _make_root(tmp_path, "b")
    (root_b / "b_only_stray").mkdir()

    config = StorageConfig(
        id="x", name="x", known_categories=["documents", "photos"],
        profiles={"full": ["documents", "other"]},
    )
    spec = SelectionSpec(profile="full")

    side_a = resolve_side(spec, root_a, config)
    side_b = resolve_side(spec, root_b, config)

    # each side's 'other' is resolved from its own filesystem contents only
    assert "a_only_stray" in side_a.other_contents
    assert "b_only_stray" not in side_a.other_contents
    assert "b_only_stray" in side_b.other_contents
    assert "a_only_stray" not in side_b.other_contents

    # 'documents' plus each side's own resolved 'other' entries make up the selectors
    assert "documents" in side_a.selectors
    assert "a_only_stray" in side_a.selectors


def test_profile_not_defined_anywhere_raises(tmp_path):
    root = _make_root(tmp_path)
    config = StorageConfig(id="x", name="x", profiles={})
    with pytest.raises(UsageError):
        resolve_side(SelectionSpec(profile="missing"), root, config)
