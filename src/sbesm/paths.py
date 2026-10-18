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


def validate_selector_containment(root: Path, selector: str) -> None:
    """Refuse a selector whose resolved path escapes the storage root --
    e.g. via a symlinked first-level entry. rsync -a doesn't follow symlinks
    *within* a synced tree, but a selector's own top-level path component is
    handed to rsync as a literal argument, so if that component (or any
    intermediate one) is itself a symlink, the OS resolves it when rsync
    opens it -- outside our control.
    """
    root = Path(root)
    target = root / selector
    resolved_root = root.resolve()
    resolved_target = target.resolve()  # safe even if target doesn't exist
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise UsageError(
            f"selector {selector!r} resolves outside the storage root "
            f"(possibly via a symlink): {target} -> {resolved_target}"
        )
