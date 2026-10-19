import tomllib
from pathlib import Path

import tomli_w


def load_local_default_excludes(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("rb") as f:
        data = tomllib.load(f)
    return list(data.get("exclude", {}).get("patterns", []))


def save_local_default_excludes(path: Path, patterns: list[str]) -> None:
    data = {"exclude": {"patterns": patterns}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data))
