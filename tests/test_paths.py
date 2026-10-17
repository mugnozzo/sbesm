import pytest

from sbesm.errors import UsageError
from sbesm.paths import validate_root_candidate


def test_rejects_nonexistent_and_uncreatable(tmp_path):
    candidate = tmp_path / "missing-parent" / "root"
    with pytest.raises(UsageError):
        validate_root_candidate(candidate)


def test_rejects_file_not_dir(tmp_path):
    candidate = tmp_path / "not_a_dir"
    candidate.write_text("i am a file")
    with pytest.raises(UsageError):
        validate_root_candidate(candidate)


def test_rejects_already_has_sbesm(tmp_path):
    candidate = tmp_path / "already_init"
    candidate.mkdir()
    (candidate / ".sbesm").mkdir()
    with pytest.raises(UsageError):
        validate_root_candidate(candidate)


def test_rejects_nested_under_sbesm_ancestor(tmp_path):
    parent = tmp_path / "storage"
    parent.mkdir()
    (parent / ".sbesm").mkdir()
    nested = parent / "subdir"
    nested.mkdir()
    with pytest.raises(UsageError):
        validate_root_candidate(nested)


def test_accepts_valid_candidate(tmp_path):
    candidate = tmp_path / "ok_root"
    candidate.mkdir()
    validate_root_candidate(candidate)


def test_accepts_creatable_missing_root(tmp_path):
    candidate = tmp_path / "to_be_created"
    validate_root_candidate(candidate)
