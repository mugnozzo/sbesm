from collections import Counter
from dataclasses import dataclass
from enum import Enum

from sbesm.db import FileRow, connect, list_file_rows
from sbesm.scanner import ScannedEntry, list_directory_paths, walk_root
from sbesm.scope import ResolvedSide


class DiffStatus(str, Enum):
    SOURCE_ONLY = "source-only"
    DEST_ONLY = "dest-only"
    EQUAL = "equal"
    SAME_CONTENT_DIFFERENT_MTIME = "same-content-different-mtime"
    DIFFERENT = "different"
    TYPE_MISMATCH = "type-mismatch"
    UNKNOWN = "unknown"


@dataclass
class DiffEntry:
    relative_path: str
    status: DiffStatus


def _trusted_hash(row: FileRow | None, scanned: ScannedEntry | None) -> str | None:
    if row is None or scanned is None:
        return None
    if scanned.kind != "regular" or row.kind != "regular":
        return None
    if row.reference_sha256 is None or row.state != "indexed":
        return None
    if row.size != scanned.size or row.mtime_ns != scanned.mtime_ns:
        # drifted since last index/verify: the stored reference can't be trusted
        # to speak for the file's *current* content.
        return None
    return row.reference_sha256


def _diff_one(
    relative_path: str,
    source_scanned: ScannedEntry | None,
    dest_scanned: ScannedEntry | None,
    source_row: FileRow | None,
    dest_row: FileRow | None,
    source_is_dir: bool = False,
    dest_is_dir: bool = False,
) -> DiffEntry:
    source_present = source_scanned is not None or source_is_dir
    dest_present = dest_scanned is not None or dest_is_dir

    if not source_present:
        return DiffEntry(relative_path, DiffStatus.DEST_ONLY)
    if not dest_present:
        return DiffEntry(relative_path, DiffStatus.SOURCE_ONLY)

    if source_is_dir or dest_is_dir:
        if source_is_dir and dest_is_dir:
            return DiffEntry(relative_path, DiffStatus.EQUAL)
        return DiffEntry(relative_path, DiffStatus.TYPE_MISMATCH)

    assert source_scanned is not None and dest_scanned is not None
    if source_scanned.kind != dest_scanned.kind:
        return DiffEntry(relative_path, DiffStatus.TYPE_MISMATCH)

    if source_scanned.kind == "symlink":
        status = (
            DiffStatus.EQUAL
            if source_scanned.symlink_target == dest_scanned.symlink_target
            else DiffStatus.DIFFERENT
        )
        return DiffEntry(relative_path, status)

    if source_scanned.kind != "regular":
        return DiffEntry(relative_path, DiffStatus.UNKNOWN)

    source_hash = _trusted_hash(source_row, source_scanned)
    dest_hash = _trusted_hash(dest_row, dest_scanned)
    if source_hash is None or dest_hash is None:
        return DiffEntry(relative_path, DiffStatus.UNKNOWN)

    if source_hash != dest_hash:
        return DiffEntry(relative_path, DiffStatus.DIFFERENT)

    if source_scanned.mtime_ns == dest_scanned.mtime_ns:
        return DiffEntry(relative_path, DiffStatus.EQUAL)
    return DiffEntry(relative_path, DiffStatus.SAME_CONTENT_DIFFERENT_MTIME)


def run_diff(source: ResolvedSide, dest: ResolvedSide) -> list[DiffEntry]:
    source_scanned = {
        e.relative_path: e
        for e in walk_root(source.root, source.selectors, source.exclude_patterns)
    }
    dest_scanned = {
        e.relative_path: e for e in walk_root(dest.root, dest.selectors, dest.exclude_patterns)
    }

    source_conn = connect(source.root / ".sbesm" / "index.sqlite")
    dest_conn = connect(dest.root / ".sbesm" / "index.sqlite")
    try:
        source_rows = {r.path: r for r in list_file_rows(source_conn)}
        dest_rows = {r.path: r for r in list_file_rows(dest_conn)}
    finally:
        source_conn.close()
        dest_conn.close()

    source_dirs = list_directory_paths(source.root, source.selectors, source.exclude_patterns)
    dest_dirs = list_directory_paths(dest.root, dest.selectors, dest.exclude_patterns)

    all_paths = sorted(set(source_scanned) | set(dest_scanned) | source_dirs | dest_dirs)
    return [
        _diff_one(
            path,
            source_scanned.get(path),
            dest_scanned.get(path),
            source_rows.get(path),
            dest_rows.get(path),
            source_is_dir=path in source_dirs,
            dest_is_dir=path in dest_dirs,
        )
        for path in all_paths
    ]


_FINDINGS_STATUSES = {
    DiffStatus.SOURCE_ONLY,
    DiffStatus.DEST_ONLY,
    DiffStatus.DIFFERENT,
    DiffStatus.TYPE_MISMATCH,
    DiffStatus.UNKNOWN,
}


def has_diff_findings(entries: list[DiffEntry]) -> bool:
    return any(e.status in _FINDINGS_STATUSES for e in entries)


def render_diff_report(entries: list[DiffEntry]) -> str:
    counts = Counter(e.status for e in entries)
    lines = [f"  {s.value}: {counts[s]}" for s in DiffStatus if counts[s]]
    if not lines:
        lines = ["  (no files found in scope)"]

    conflicts = [e.relative_path for e in entries if e.status == DiffStatus.DIFFERENT]
    if conflicts:
        lines.append("  content conflicts (same path, different content):")
        lines.extend(f"    {p}" for p in conflicts)

    dest_only = [e.relative_path for e in entries if e.status == DiffStatus.DEST_ONLY]
    if dest_only:
        lines.append(
            "  destination-only (not necessarily historically deleted from source):"
        )
        lines.extend(f"    {p}" for p in dest_only)

    return "\n".join(lines)
