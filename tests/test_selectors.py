import pytest

from sbesm.errors import UsageError
from sbesm.selectors import normalize_selection, normalize_selector

# --- 1.5.5 selector normalization -------------------------------------------


def test_rejects_absolute_path():
    with pytest.raises(UsageError):
        normalize_selector("/etc/passwd")


def test_rejects_dotdot_traversal():
    with pytest.raises(UsageError):
        normalize_selector("photos/../../etc")


def test_rejects_sbesm_reference():
    with pytest.raises(UsageError):
        normalize_selector(".sbesm/config.toml")


def test_normalizes_redundant_segments():
    assert normalize_selector("./photos//raw/./") == "photos/raw"


# --- 1.5.6 overlap/escape handling -------------------------------------------


def test_collapses_nested_selector_into_broader_with_warning():
    result = normalize_selection(["photos", "photos/raw"])
    assert result.paths == ["photos"]
    assert len(result.warnings) == 1
    assert "photos/raw" in result.warnings[0]
    assert "photos" in result.warnings[0]


def test_independent_selectors_are_not_collapsed():
    result = normalize_selection(["photos", "documents"])
    assert result.paths == ["documents", "photos"]
    assert result.warnings == []


def test_duplicate_selectors_are_deduplicated_without_warning():
    result = normalize_selection(["photos", "photos"])
    assert result.paths == ["photos"]
    assert result.warnings == []


def test_escape_in_one_of_several_selectors_still_raises():
    with pytest.raises(UsageError):
        normalize_selection(["photos", "../etc"])
