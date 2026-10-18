import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w


@dataclass
class StorageConfig:
    id: str
    name: str
    filesystem_uuid: str | None = None
    known_categories: list[str] = field(default_factory=list)
    profiles: dict[str, list[str]] = field(default_factory=dict)
    preserve_partial: bool = True
    delete_by_default: bool = False
    hashing_algorithm: str = "sha256"
    mtime_tolerance_ns: int | None = None  # None = auto-detect from filesystem type


def write_storage_config(path: Path, config: StorageConfig) -> None:
    sync_table: dict[str, object] = {
        "preserve_partial": config.preserve_partial,
        "delete_by_default": config.delete_by_default,
    }
    if config.mtime_tolerance_ns is not None:
        sync_table["mtime_tolerance_ns"] = config.mtime_tolerance_ns

    data = {
        "storage": {
            "id": config.id,
            "name": config.name,
            "filesystem_uuid": config.filesystem_uuid or "",
        },
        "categories": {
            "known": config.known_categories,
        },
        "profiles": {
            name: {"categories": categories}
            for name, categories in config.profiles.items()
        },
        "sync": sync_table,
        "hashing": {
            "algorithm": config.hashing_algorithm,
        },
    }
    path.write_text(tomli_w.dumps(data))


def read_storage_config(path: Path) -> StorageConfig:
    with path.open("rb") as f:
        data = tomllib.load(f)

    storage = data.get("storage", {})
    categories = data.get("categories", {})
    profiles_raw = data.get("profiles", {})
    sync = data.get("sync", {})
    hashing = data.get("hashing", {})

    return StorageConfig(
        id=storage["id"],
        name=storage["name"],
        filesystem_uuid=storage.get("filesystem_uuid") or None,
        known_categories=list(categories.get("known", [])),
        profiles={
            name: list(profile.get("categories", []))
            for name, profile in profiles_raw.items()
        },
        preserve_partial=sync.get("preserve_partial", True),
        delete_by_default=sync.get("delete_by_default", False),
        hashing_algorithm=hashing.get("algorithm", "sha256"),
        mtime_tolerance_ns=sync.get("mtime_tolerance_ns"),
    )
