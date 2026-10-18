import fcntl
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sbesm.errors import IOFailureError
from sbesm.migrations import MIGRATIONS, apply_migrations


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def storage_write_lock(sbesm_dir: Path) -> Iterator[None]:
    lock_path = sbesm_dir / ".lock"
    lock_path.touch(exist_ok=True)
    with open(lock_path, "w") as fd:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise IOFailureError(
                f"storage {sbesm_dir} is busy (locked by another process)"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM storage_meta WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO storage_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def start_run(conn: sqlite3.Connection, command: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs(command, started_at, finished_at, outcome, details_json) "
        "VALUES (?, ?, NULL, NULL, NULL)",
        (command, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    run_id = cur.lastrowid
    assert run_id is not None
    return run_id


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    outcome: str,
    details_json: str | None = None,
) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, outcome = ?, details_json = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), outcome, details_json, run_id),
    )
    conn.commit()


def initialize_index_db(db_path: Path, storage_id: str) -> None:
    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS)
        if get_meta(conn, "storage_id") is None:
            set_meta(conn, "storage_id", storage_id)
            set_meta(conn, "schema_version", str(len(MIGRATIONS)))
            set_meta(conn, "created_at", datetime.now(UTC).isoformat())
    finally:
        conn.close()


_FILE_COLUMNS = (
    "path",
    "kind",
    "size",
    "mtime_ns",
    "reference_sha256",
    "reference_size",
    "reference_mtime_ns",
    "hashed_at",
    "last_seen_at",
    "state",
    "candidate_sha256",
    "symlink_target",
)


@dataclass
class FileRow:
    path: str
    kind: str
    size: int | None
    mtime_ns: int | None
    reference_sha256: str | None
    reference_size: int | None
    reference_mtime_ns: int | None
    hashed_at: str | None
    last_seen_at: str | None
    state: str
    candidate_sha256: str | None
    symlink_target: str | None = None


def get_file_row(conn: sqlite3.Connection, path: str) -> FileRow | None:
    row = conn.execute(
        f"SELECT {', '.join(_FILE_COLUMNS)} FROM files WHERE path = ?", (path,)
    ).fetchone()
    return FileRow(*row) if row is not None else None


def list_file_rows(conn: sqlite3.Connection) -> list[FileRow]:
    rows = conn.execute(
        f"SELECT {', '.join(_FILE_COLUMNS)} FROM files ORDER BY path"
    ).fetchall()
    return [FileRow(*row) for row in rows]


def upsert_file_row(conn: sqlite3.Connection, row: FileRow) -> None:
    columns = ", ".join(_FILE_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in _FILE_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _FILE_COLUMNS if c != "path")
    conn.execute(
        f"INSERT INTO files ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(path) DO UPDATE SET {updates}",
        asdict(row),
    )
