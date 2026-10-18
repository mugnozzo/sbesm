import pytest

from sbesm.db import (
    FileRow,
    connect,
    finish_run,
    get_file_row,
    get_meta,
    list_file_rows,
    set_meta,
    start_run,
    storage_write_lock,
    upsert_file_row,
)
from sbesm.errors import IOFailureError
from sbesm.migrations import MIGRATIONS, apply_migrations

# --- 2.1.1 connection helper -------------------------------------------------


def test_connect_sets_expected_pragmas(tmp_path):
    conn = connect(tmp_path / "test.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()


# --- 2.1.2/2.1.3 migration framework + base schema --------------------------


def test_apply_migrations_creates_base_schema(tmp_path):
    conn = connect(tmp_path / "test.sqlite")
    apply_migrations(conn, MIGRATIONS)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"storage_meta", "files", "runs"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    conn.close()


def test_apply_migrations_is_idempotent(tmp_path):
    conn = connect(tmp_path / "test.sqlite")
    apply_migrations(conn, MIGRATIONS)
    apply_migrations(conn, MIGRATIONS)  # should not raise or re-run scripts
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    conn.close()


# --- 2.1.4 single-writer lock -----------------------------------------------


def test_write_lock_blocks_concurrent_writer(tmp_path):
    sbesm_dir = tmp_path / ".sbesm"
    sbesm_dir.mkdir()
    with storage_write_lock(sbesm_dir), pytest.raises(IOFailureError), storage_write_lock(sbesm_dir):
        pass


def test_write_lock_released_after_context(tmp_path):
    sbesm_dir = tmp_path / ".sbesm"
    sbesm_dir.mkdir()
    with storage_write_lock(sbesm_dir):
        pass
    with storage_write_lock(sbesm_dir):
        pass


# --- 2.1.5 storage_meta accessors -------------------------------------------


def test_meta_round_trip(tmp_path):
    conn = connect(tmp_path / "test.sqlite")
    apply_migrations(conn, MIGRATIONS)
    assert get_meta(conn, "storage_id") is None
    set_meta(conn, "storage_id", "abc-123")
    assert get_meta(conn, "storage_id") == "abc-123"
    set_meta(conn, "storage_id", "replaced")
    assert get_meta(conn, "storage_id") == "replaced"
    conn.close()


# --- 2.1.6 runs helpers ------------------------------------------------------


def test_run_without_finish_leaves_finished_at_null(tmp_path):
    conn = connect(tmp_path / "test.sqlite")
    apply_migrations(conn, MIGRATIONS)
    run_id = start_run(conn, "index")
    row = conn.execute(
        "SELECT finished_at FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row[0] is None
    conn.close()


def test_finish_run_sets_outcome_and_finished_at(tmp_path):
    conn = connect(tmp_path / "test.sqlite")
    apply_migrations(conn, MIGRATIONS)
    run_id = start_run(conn, "index")
    finish_run(conn, run_id, "success")
    row = conn.execute(
        "SELECT finished_at, outcome FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "success"
    conn.close()


# --- 2.1.7 reopen/upgrade preserves data -------------------------------------


def test_reopen_after_new_migration_preserves_existing_data(tmp_path):
    db_path = tmp_path / "test.sqlite"
    conn = connect(db_path)
    apply_migrations(conn, MIGRATIONS)
    row = FileRow(
        path="a.txt",
        kind="regular",
        size=5,
        mtime_ns=123,
        reference_sha256="deadbeef",
        reference_size=5,
        reference_mtime_ns=123,
        hashed_at="2026-01-01T00:00:00+00:00",
        last_seen_at="2026-01-01T00:00:00+00:00",
        state="indexed",
        candidate_sha256=None,
    )
    upsert_file_row(conn, row)
    conn.commit()
    conn.close()

    extra_migrations = [*MIGRATIONS, "ALTER TABLE files ADD COLUMN dummy_new_col TEXT;"]
    conn2 = connect(db_path)
    apply_migrations(conn2, extra_migrations)
    reloaded = get_file_row(conn2, "a.txt")
    assert reloaded is not None
    assert reloaded.reference_sha256 == "deadbeef"
    assert list_file_rows(conn2) == [reloaded]
    conn2.close()
