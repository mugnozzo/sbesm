import os
import threading
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from sbesm.config import StorageConfig
from sbesm.errors import (
    AmbiguousStorageError,
    StorageIdentityMismatchError,
    StorageUnavailableError,
)

MountEntry = tuple[str, str, str]  # (device, mountpoint, fstype)


def _read_mounts(proc_mounts_path: str = "/proc/mounts") -> list[MountEntry]:
    entries: list[MountEntry] = []
    with open(proc_mounts_path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            device, mountpoint, fstype = parts[0], parts[1], parts[2]
            mountpoint = mountpoint.replace("\\040", " ")
            entries.append((device, mountpoint, fstype))
    return entries


def _find_mount_entry(
    path: Path, proc_mounts_path: str = "/proc/mounts"
) -> MountEntry | None:
    resolved = Path(path).resolve()
    best: MountEntry | None = None
    best_len = -1
    for entry in _read_mounts(proc_mounts_path):
        mountpoint = Path(entry[1])
        is_match = resolved == mountpoint or mountpoint in resolved.parents
        if is_match and len(str(mountpoint)) > best_len:
            best = entry
            best_len = len(str(mountpoint))
    return best


def detect_filesystem_type(path: Path, proc_mounts_path: str = "/proc/mounts") -> str | None:
    entry = _find_mount_entry(path, proc_mounts_path)
    return entry[2] if entry is not None else None


def detect_filesystem_uuid(
    path: Path,
    proc_mounts_path: str = "/proc/mounts",
    by_uuid_dir: str = "/dev/disk/by-uuid",
) -> str | None:
    entry = _find_mount_entry(path, proc_mounts_path)
    if entry is None:
        return None
    device, _mountpoint, _fstype = entry

    device_real = os.path.realpath(device)
    try:
        candidates = os.listdir(by_uuid_dir)
    except OSError:
        return None

    for name in candidates:
        link_path = os.path.join(by_uuid_dir, name)
        if os.path.realpath(link_path) == device_real:
            return name
    return None


def is_mounted_and_responsive(
    path: Path,
    timeout_s: float = 5.0,
    stat_func: Callable[[Path], os.stat_result] = os.stat,
) -> bool:
    result: dict[str, bool] = {}

    def _check() -> None:
        try:
            stat_func(path)
            result["ok"] = True
        except OSError:
            result["ok"] = False

    thread = threading.Thread(target=_check, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return False
    return result.get("ok", False)


def validate_storage_identity(
    config: StorageConfig,
    root: Path,
    timeout_s: float = 5.0,
    proc_mounts_path: str = "/proc/mounts",
    by_uuid_dir: str = "/dev/disk/by-uuid",
) -> None:
    if not is_mounted_and_responsive(root, timeout_s=timeout_s):
        raise StorageUnavailableError(f"{root} is not mounted or not responding")

    current_uuid = detect_filesystem_uuid(root, proc_mounts_path, by_uuid_dir)
    if config.filesystem_uuid and current_uuid and config.filesystem_uuid != current_uuid:
        raise StorageIdentityMismatchError(
            f"filesystem UUID mismatch for {root}: "
            f"expected {config.filesystem_uuid}, found {current_uuid}"
        )


def check_storage_id_marker(config: StorageConfig, sbesm_dir: Path) -> None:
    marker_path = sbesm_dir / "storage_id"
    marker_value = marker_path.read_text().strip()
    if marker_value != config.id:
        raise AmbiguousStorageError(
            f"storage_id marker ({marker_value}) does not match "
            f"config.toml id ({config.id}) at {sbesm_dir}"
        )


def find_cloned_ids(
    candidates: list[tuple[Path, str]]
) -> list[tuple[str, list[Path]]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for root, storage_id in candidates:
        groups[storage_id].append(root)
    return [(sid, roots) for sid, roots in groups.items() if len(roots) >= 2]
