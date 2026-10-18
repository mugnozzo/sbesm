from pathlib import Path

from sbesm.errors import StorageNotFoundError
from sbesm.registry import load_registry
from sbesm.xdg import config_home


def resolve_storage(identifier: str, registry_path: Path | None = None) -> Path:
    candidate = Path(identifier)
    if candidate.is_dir() and (candidate / ".sbesm").is_dir():
        return candidate

    path = registry_path if registry_path is not None else (config_home() / "registry.toml")
    entries = load_registry(path)
    if identifier in entries:
        return Path(entries[identifier].last_known_root)

    raise StorageNotFoundError(
        f"{identifier!r} is not a registered storage name or a valid storage path"
    )
