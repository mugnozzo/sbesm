import os
from pathlib import Path

from sbesm.errors import UsageError


def validate_root_candidate(path: Path) -> None:
    path = Path(path)

    if path.exists():
        if not path.is_dir():
            raise UsageError(f"{path} exists and is not a directory")
        if (path / ".sbesm").exists():
            raise UsageError(
                f"{path} already contains a .sbesm directory (already initialized)"
            )
    else:
        parent = path.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise UsageError(
                f"{path} does not exist and cannot be created "
                f"(parent {parent} is missing or not writable)"
            )

    for ancestor in path.resolve().parents:
        if (ancestor / ".sbesm").is_dir():
            raise UsageError(
                f"{path} is nested under an existing SBESM storage at {ancestor}"
            )
