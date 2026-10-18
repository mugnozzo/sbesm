import pytest

from sbesm.errors import UsageError
from sbesm.paths import validate_root_candidate, validate_selector_containment


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


# --- validate_selector_containment ------------------------------------------


def test_containment_allows_normal_selector(tmp_path):
    root = tmp_path / "root"
    (root / "documents").mkdir(parents=True)
    validate_selector_containment(root, "documents")  # should not raise


def test_containment_allows_nonexistent_selector(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    validate_selector_containment(root, "not_created_yet")  # should not raise


def test_containment_rejects_symlink_escaping_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "documents").symlink_to(outside)

    with pytest.raises(UsageError):
        validate_selector_containment(root, "documents")


def test_containment_rejects_broken_symlink_escaping_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "documents").symlink_to(tmp_path / "does_not_exist_at_all")

    with pytest.raises(UsageError):
        validate_selector_containment(root, "documents")


def test_containment_allows_symlink_pointing_inside_root(tmp_path):
    root = tmp_path / "root"
    real = root / "real_archive"
    real.mkdir(parents=True)
    (root / "documents").symlink_to(real)

    validate_selector_containment(root, "documents")  # should not raise


def test_containment_catches_escape_via_deep_selector(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "documents").symlink_to(outside)

    with pytest.raises(UsageError):
        validate_selector_containment(root, "documents/subdir")
