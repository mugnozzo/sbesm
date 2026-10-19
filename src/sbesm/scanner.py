import os
import stat
from dataclasses import dataclass
from pathlib import Path

from sbesm.exclude import is_name_excluded
from sbesm.selectors import normalize_selection

_EXCLUDED_NAMES = {".sbesm", ".rsync-partial"}


@dataclass
class ScannedEntry:
    relative_path: str
    kind: str  # "regular" | "symlink" | "unreadable"
    size: int | None
    mtime_ns: int | None
    absolute_path: Path
    symlink_target: str | None = None


def _classify_entry(path: Path, rel_path: str) -> ScannedEntry:
    try:
        st = path.lstat()
    except OSError:
        return ScannedEntry(rel_path, "unreadable", None, None, path)

    if stat.S_ISLNK(st.st_mode):
        try:
            target = os.readlink(path)
        except OSError:
            target = None
        return ScannedEntry(rel_path, "symlink", st.st_size, st.st_mtime_ns, path, target)

    if stat.S_ISREG(st.st_mode):
        return ScannedEntry(rel_path, "regular", st.st_size, st.st_mtime_ns, path)

    # directories are handled by the caller; anything else (socket/fifo/device/...)
    # is treated as unreadable/non-hashable.
    return ScannedEntry(rel_path, "unreadable", None, None, path)


def _walk_dir(
    dir_path: Path, rel_prefix: str, entries: list[ScannedEntry], exclude_patterns: list[str]
) -> None:
    try:
        children = sorted(dir_path.iterdir(), key=lambda p: p.name)
    except OSError:
        return

    for child in children:
        if child.name in _EXCLUDED_NAMES or is_name_excluded(child.name, exclude_patterns):
            continue
        rel_path = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
        if child.is_dir() and not child.is_symlink():
            _walk_dir(child, rel_path, entries, exclude_patterns)
        else:
            entries.append(_classify_entry(child, rel_path))


def walk_root(
    root: Path, scope: list[str] | None = None, exclude_patterns: list[str] | None = None
) -> list[ScannedEntry]:
    root = Path(root)
    entries: list[ScannedEntry] = []
    patterns = exclude_patterns or []

    if scope is None:
        _walk_dir(root, "", entries, patterns)
    else:
        normalized = normalize_selection(scope)
        for selector in normalized.paths:
            target = root / selector
            if target.is_dir() and not target.is_symlink():
                _walk_dir(target, selector, entries, patterns)
            elif target.exists() or target.is_symlink():
                entries.append(_classify_entry(target, selector))
            # a selector that doesn't exist on disk yields no entries here;
            # "missing" is detected at the indexing layer by diffing against
            # existing DB rows, not by the scanner.

    return sorted(entries, key=lambda e: e.relative_path)


def _collect_directories(
    dir_path: Path, rel_prefix: str, dirs: set[str], exclude_patterns: list[str]
) -> None:
    try:
        children = sorted(dir_path.iterdir(), key=lambda p: p.name)
    except OSError:
        return

    for child in children:
        if child.name in _EXCLUDED_NAMES or is_name_excluded(child.name, exclude_patterns):
            continue
        if child.is_dir() and not child.is_symlink():
            rel_path = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
            dirs.add(rel_path)
            _collect_directories(child, rel_path, dirs, exclude_patterns)


def list_directory_paths(
    root: Path, scope: list[str] | None = None, exclude_patterns: list[str] | None = None
) -> set[str]:
    """Relative paths of every directory within scope (excluding the root itself).

    Used by diff to detect a directory on one side colliding with a regular
    file/symlink leaf at the same relative path on the other side -- a case
    `walk_root` alone can't reveal, since it never emits an entry for a
    directory itself, only for its leaf contents.
    """
    root = Path(root)
    dirs: set[str] = set()
    patterns = exclude_patterns or []

    if scope is None:
        _collect_directories(root, "", dirs, patterns)
    else:
        for selector in normalize_selection(scope).paths:
            target = root / selector
            if target.is_dir() and not target.is_symlink():
                dirs.add(selector)
                _collect_directories(target, selector, dirs, patterns)

    return dirs
