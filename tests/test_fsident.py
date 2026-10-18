import os
import time

import pytest

from sbesm.config import StorageConfig
from sbesm.errors import (
    AmbiguousStorageError,
    StorageIdentityMismatchError,
    StorageUnavailableError,
)
from sbesm.fsident import (
    check_storage_id_marker,
    detect_filesystem_type,
    detect_filesystem_uuid,
    find_cloned_ids,
    is_mounted_and_responsive,
    validate_storage_identity,
)

# --- 1.3.1 block-device UUID lookup -----------------------------------------


def test_detect_filesystem_type_returns_fstype_of_matching_mount(tmp_path):
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    mounts_file = tmp_path / "mounts"
    mounts_file.write_text(f"/dev/sdb1 {mnt} ext4 rw,relatime 0 0\n")

    assert detect_filesystem_type(mnt, proc_mounts_path=str(mounts_file)) == "ext4"


def test_detect_filesystem_type_returns_none_when_unresolved(tmp_path):
    mounts_file = tmp_path / "mounts"
    mounts_file.write_text("/dev/sdb1 /somewhere/else ext4 rw,relatime 0 0\n")
    assert detect_filesystem_type(tmp_path, proc_mounts_path=str(mounts_file)) is None


def test_detect_filesystem_uuid_finds_matching_mount(tmp_path):
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    subdir = mnt / "sub"
    subdir.mkdir()

    mounts_file = tmp_path / "mounts"
    mounts_file.write_text(f"/dev/sdb1 {mnt} ext4 rw,relatime 0 0\n")

    by_uuid_dir = tmp_path / "by-uuid"
    by_uuid_dir.mkdir()
    (by_uuid_dir / "ABCD-1234").symlink_to("/dev/sdb1")

    found = detect_filesystem_uuid(
        subdir, proc_mounts_path=str(mounts_file), by_uuid_dir=str(by_uuid_dir)
    )
    assert found == "ABCD-1234"


def test_detect_filesystem_uuid_returns_none_when_no_mount_matches(tmp_path):
    mounts_file = tmp_path / "mounts"
    mounts_file.write_text("/dev/sdb1 /somewhere/else ext4 rw,relatime 0 0\n")

    found = detect_filesystem_uuid(
        tmp_path, proc_mounts_path=str(mounts_file), by_uuid_dir=str(tmp_path)
    )
    assert found is None


# --- 1.3.2 mount presence/liveness check ------------------------------------


def test_missing_mount_fails_fast(tmp_path):
    missing = tmp_path / "does_not_exist"
    start = time.monotonic()
    assert is_mounted_and_responsive(missing, timeout_s=5.0) is False
    assert time.monotonic() - start < 1.0


def test_hanging_stat_treated_as_not_live_within_timeout(tmp_path):
    def hanging_stat(_path):
        time.sleep(2)
        return os.stat_result((0,) * 10)

    start = time.monotonic()
    result = is_mounted_and_responsive(
        tmp_path, timeout_s=0.05, stat_func=hanging_stat
    )
    elapsed = time.monotonic() - start
    assert result is False
    assert elapsed < 1.0


def test_live_mount_is_responsive(tmp_path):
    assert is_mounted_and_responsive(tmp_path, timeout_s=5.0) is True


# --- 1.3.3 identity validation policy ---------------------------------------


def test_validate_storage_identity_matching_uuid_passes(tmp_path, monkeypatch):
    from sbesm import fsident

    monkeypatch.setattr(fsident, "detect_filesystem_uuid", lambda *a, **k: "SAME-UUID")
    config = StorageConfig(id="x", name="x", filesystem_uuid="SAME-UUID")
    validate_storage_identity(config, tmp_path)  # should not raise


def test_validate_storage_identity_mismatched_uuid_raises(tmp_path, monkeypatch):
    from sbesm import fsident

    monkeypatch.setattr(fsident, "detect_filesystem_uuid", lambda *a, **k: "OTHER-UUID")
    config = StorageConfig(id="x", name="x", filesystem_uuid="SAME-UUID")
    with pytest.raises(StorageIdentityMismatchError):
        validate_storage_identity(config, tmp_path)


def test_validate_storage_identity_not_mounted_raises(tmp_path, monkeypatch):
    from sbesm import fsident

    monkeypatch.setattr(fsident, "is_mounted_and_responsive", lambda *a, **k: False)
    config = StorageConfig(id="x", name="x", filesystem_uuid="SAME-UUID")
    with pytest.raises(StorageUnavailableError):
        validate_storage_identity(config, tmp_path)


# --- 1.3.4 storage-id marker cross-check ------------------------------------


def test_marker_cross_check_matching_ids_passes(tmp_path):
    sbesm_dir = tmp_path / ".sbesm"
    sbesm_dir.mkdir()
    (sbesm_dir / "storage_id").write_text("abc-123")
    config = StorageConfig(id="abc-123", name="x")
    check_storage_id_marker(config, sbesm_dir)  # should not raise


def test_marker_cross_check_mismatched_ids_raises(tmp_path):
    sbesm_dir = tmp_path / ".sbesm"
    sbesm_dir.mkdir()
    (sbesm_dir / "storage_id").write_text("abc-123")
    config = StorageConfig(id="different-id", name="x")
    with pytest.raises(AmbiguousStorageError):
        check_storage_id_marker(config, sbesm_dir)


# --- 1.3.5 cloned/duplicate-ID detection -------------------------------------


def test_find_cloned_ids_detects_shared_id(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_c = tmp_path / "c"
    clones = find_cloned_ids(
        [(root_a, "shared-id"), (root_b, "shared-id"), (root_c, "unique-id")]
    )
    assert clones == [("shared-id", [root_a, root_b])]


def test_find_cloned_ids_no_clones(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    clones = find_cloned_ids([(root_a, "id-1"), (root_b, "id-2")])
    assert clones == []
