from pathlib import Path

from sbesm.config import StorageConfig
from sbesm.errors import UsageError


def discover_categories(root: Path) -> list[str]:
    return sorted(
        entry.name
        for entry in Path(root).iterdir()
        if entry.is_dir() and entry.name != ".sbesm"
    )


def resolve_other(root: Path, known: list[str]) -> list[str]:
    known_set = set(known)
    unlisted: list[str] = []
    for entry in Path(root).iterdir():
        if entry.name == ".sbesm":
            continue
        if entry.is_dir():
            if entry.name not in known_set:
                unlisted.append(entry.name)
        else:
            unlisted.append(entry.name)
    return sorted(unlisted)


def validate_profiles(config: StorageConfig) -> None:
    known_set = set(config.known_categories)
    for profile_name, categories in config.profiles.items():
        for category in categories:
            if category != "other" and category not in known_set:
                raise UsageError(
                    f"profile {profile_name!r} references unknown category "
                    f"{category!r} (not in known categories and not 'other')"
                )
