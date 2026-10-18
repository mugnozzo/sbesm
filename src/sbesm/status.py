import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sbesm.categories import discover_categories
from sbesm.config import StorageConfig
from sbesm.db import list_file_rows


@dataclass
class CategoryPresence:
    expected: set[str]
    present: set[str]
    indexed: set[str]


def compute_category_presence(root: Path, config: StorageConfig, conn: sqlite3.Connection) -> CategoryPresence:
    expected = set(config.known_categories)
    present = set(discover_categories(root))
    # a row's first path segment is only a "category" when the row is
    # actually nested under a first-level directory; a loose top-level file
    # has no "/" in its path and must not be reported as if it were one.
    indexed = {row.path.split("/", 1)[0] for row in list_file_rows(conn) if "/" in row.path}
    return CategoryPresence(expected=expected, present=present, indexed=indexed)


def compute_counts(conn: sqlite3.Connection, scope: str | None = None) -> tuple[dict[str, int], int]:
    if scope:
        rows = conn.execute(
            "SELECT state, COUNT(*), COALESCE(SUM(size), 0) FROM files "
            "WHERE path = ? OR path LIKE ? GROUP BY state",
            (scope, f"{scope}/%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT state, COUNT(*), COALESCE(SUM(size), 0) FROM files GROUP BY state"
        ).fetchall()

    counts: dict[str, int] = {}
    total_bytes = 0
    for state, count, size_sum in rows:
        counts[state] = count
        total_bytes += size_sum
    return counts, total_bytes


@dataclass
class RunSummary:
    started_at: str
    finished_at: str | None
    outcome: str | None


def last_run_summary(conn: sqlite3.Connection) -> dict[str, RunSummary | None]:
    summary: dict[str, RunSummary | None] = {}
    for command in ("index", "verify"):
        row = conn.execute(
            "SELECT started_at, finished_at, outcome FROM runs WHERE command = ? "
            "ORDER BY id DESC LIMIT 1",
            (command,),
        ).fetchone()
        summary[command] = RunSummary(*row) if row else None
    return summary
