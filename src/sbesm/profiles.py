import tomllib
from pathlib import Path

import tomli_w

from sbesm.config import StorageConfig
from sbesm.errors import UsageError


def load_local_profiles(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    profiles_raw = data.get("profiles", {})
    return {
        name: list(profile.get("categories", []))
        for name, profile in profiles_raw.items()
    }


def save_local_profiles(path: Path, profiles: dict[str, list[str]]) -> None:
    data = {
        "profiles": {
            name: {"categories": categories} for name, categories in profiles.items()
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data))


def resolve_profile(
    name: str,
    storage_config: StorageConfig,
    local_profiles: dict[str, list[str]] | None = None,
) -> list[str]:
    local_profiles = local_profiles or {}
    if name in local_profiles:
        return list(local_profiles[name])
    if name in storage_config.profiles:
        return list(storage_config.profiles[name])
    raise UsageError(f"profile {name!r} is not defined in local or storage config")
