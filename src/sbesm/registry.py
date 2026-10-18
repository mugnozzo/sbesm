import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from sbesm.fsident import find_cloned_ids, is_mounted_and_responsive


@dataclass
class RegistryEntry:
    name: str
    storage_id: str
    last_known_root: str
    filesystem_uuid: str | None
    last_seen_at: str


def load_registry(path: Path) -> dict[str, RegistryEntry]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    storages = data.get("storages", {})
    return {
        name: RegistryEntry(
            name=name,
            storage_id=entry["storage_id"],
            last_known_root=entry["last_known_root"],
            filesystem_uuid=entry.get("filesystem_uuid") or None,
            last_seen_at=entry["last_seen_at"],
        )
        for name, entry in storages.items()
    }


def save_registry(path: Path, entries: dict[str, RegistryEntry]) -> None:
    data = {
        "storages": {
            name: {
                "storage_id": entry.storage_id,
                "last_known_root": entry.last_known_root,
                "filesystem_uuid": entry.filesystem_uuid or "",
                "last_seen_at": entry.last_seen_at,
            }
            for name, entry in entries.items()
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data))


def upsert_entry(path: Path, entry: RegistryEntry) -> None:
    entries = load_registry(path)
    entries[entry.name] = entry
    save_registry(path, entries)


def classify_registry(entries: dict[str, RegistryEntry]) -> dict[str, str]:
    cloned = find_cloned_ids(
        [(Path(entry.last_known_root), entry.storage_id) for entry in entries.values()]
    )
    cloned_storage_ids = {storage_id for storage_id, _roots in cloned}

    result: dict[str, str] = {}
    for name, entry in entries.items():
        if entry.storage_id in cloned_storage_ids:
            result[name] = "ambiguous"
        elif is_mounted_and_responsive(Path(entry.last_known_root)):
            result[name] = "available"
        else:
            result[name] = "unavailable"
    return result
