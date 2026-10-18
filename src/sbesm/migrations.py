import sqlite3

MIGRATION_0001_BASE_SCHEMA = """
CREATE TABLE storage_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE files (
    path TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    size INTEGER,
    mtime_ns INTEGER,
    reference_sha256 TEXT,
    reference_size INTEGER,
    reference_mtime_ns INTEGER,
    hashed_at TEXT,
    last_seen_at TEXT,
    state TEXT NOT NULL,
    candidate_sha256 TEXT
);
CREATE INDEX idx_files_reference_sha256 ON files(reference_sha256);
CREATE INDEX idx_files_state ON files(state);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    command TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,
    details_json TEXT
);
"""

MIGRATION_0002_SYMLINK_TARGET = """
ALTER TABLE files ADD COLUMN symlink_target TEXT;
"""

MIGRATIONS = [MIGRATION_0001_BASE_SCHEMA, MIGRATION_0002_SYMLINK_TARGET]


def apply_migrations(
    conn: sqlite3.Connection, migrations: list[str] = MIGRATIONS
) -> None:
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    for idx in range(current_version, len(migrations)):
        conn.executescript(migrations[idx])
        conn.execute(f"PRAGMA user_version = {idx + 1}")
        conn.commit()
