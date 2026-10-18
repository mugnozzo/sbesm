import os
import stat
from dataclasses import dataclass
from pathlib import Path

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


def _walk_dir(dir_path: Path, rel_prefix: str, entries: list[ScannedEntry]) -> None:
    try:
        children = sorted(dir_path.iterdir(), key=lambda p: p.name)
    except OSError:
        return

    for child in children:
        if child.name in _EXCLUDED_NAMES:
            continue
        rel_path = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
        if child.is_dir() and not child.is_symlink():
            _walk_dir(child, rel_path, entries)
        else:
            entries.append(_classify_entry(child, rel_path))


def walk_root(root: Path, scope: list[str] | None = None) -> list[ScannedEntry]:
    root = Path(root)
    entries: list[ScannedEntry] = []

    if scope is None:
        _walk_dir(root, "", entries)
    else:
        normalized = normalize_selection(scope)
        for selector in normalized.paths:
            target = root / selector
            if target.is_dir() and not target.is_symlink():
                _walk_dir(target, selector, entries)
            elif target.exists() or target.is_symlink():
                entries.append(_classify_entry(target, selector))
            # a selector that doesn't exist on disk yields no entries here;
            # "missing" is detected at the indexing layer by diffing against
            # existing DB rows, not by the scanner.

    return sorted(entries, key=lambda e: e.relative_path)
