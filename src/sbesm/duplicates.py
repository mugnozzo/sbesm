import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sbesm.db import list_file_rows
from sbesm.hashing import NotHashableError, UnstableFileError, hash_file_stable


@dataclass
class DuplicateGroup:
    sha256: str
    size: int | None
    paths: list[str]


def find_duplicates(
    conn: sqlite3.Connection, *, min_size: int = 0, scope: str | None = None
) -> list[DuplicateGroup]:
    groups: dict[tuple[str, int | None], list[str]] = defaultdict(list)
    for row in list_file_rows(conn):
        if row.kind != "regular" or row.reference_sha256 is None:
            continue
        if row.reference_size is not None and row.reference_size < min_size:
            continue
        if scope is not None and not (row.path == scope or row.path.startswith(scope + "/")):
            continue
        groups[(row.reference_sha256, row.reference_size)].append(row.path)

    return [
        DuplicateGroup(sha256=sha, size=size, paths=sorted(paths))
        for (sha, size), paths in groups.items()
        if len(paths) >= 2
    ]


@dataclass
class VerifiedDuplicateGroup:
    sha256: str
    size: int | None
    verified_paths: list[str]
    stale_paths: list[str]


def verify_duplicate_groups(
    root: Path, groups: list[DuplicateGroup]
) -> list[VerifiedDuplicateGroup]:
    results = []
    for group in groups:
        verified_paths = []
        stale_paths = []
        for path in group.paths:
            try:
                fresh_hash = hash_file_stable(root / path)
            except (OSError, NotHashableError, UnstableFileError):
                fresh_hash = None
            if fresh_hash == group.sha256:
                verified_paths.append(path)
            else:
                stale_paths.append(path)
        results.append(
            VerifiedDuplicateGroup(
                sha256=group.sha256,
                size=group.size,
                verified_paths=verified_paths,
                stale_paths=stale_paths,
            )
        )
    return results
