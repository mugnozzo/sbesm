import os

import pytest

from sbesm.accept_cmd import cmd_accept
from sbesm.db import connect, get_file_row
from sbesm.errors import UsageError
from sbesm.indexing import run_index
from sbesm.migrations import MIGRATIONS, apply_migrations


def _make_storage(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    sbesm_dir = root / ".sbesm"
    sbesm_dir.mkdir()
    db_path = sbesm_dir / "index.sqlite"
    conn = connect(db_path)
    apply_migrations(conn, MIGRATIONS)
    conn.close()
    return root, db_path


def test_accept_preview_shows_old_and_new_without_writing(tmp_path):
    root, db_path = _make_storage(tmp_path)
    path = root / "a.txt"
    path.write_text("original")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    before = get_file_row(conn, "a.txt")
    conn.close()

    st = path.stat()
    path.write_bytes(b"changed!")
    os.utime(path, ns=(st.st_mtime_ns, st.st_mtime_ns))

    result = cmd_accept(root, db_path, "a.txt", apply=False)
    assert result.old_hash == before.reference_sha256
    assert result.new_hash != before.reference_sha256
    assert result.applied is False

    conn = connect(db_path)
    after = get_file_row(conn, "a.txt")
    conn.close()
    assert after.reference_sha256 == before.reference_sha256  # untouched by preview


def test_accept_apply_replaces_reference_hash(tmp_path):
    root, db_path = _make_storage(tmp_path)
    path = root / "a.txt"
    path.write_text("original")
    run_index(root, db_path, apply=True)

    st = path.stat()
    path.write_bytes(b"changed!")
    os.utime(path, ns=(st.st_mtime_ns, st.st_mtime_ns))

    result = cmd_accept(root, db_path, "a.txt", apply=True)
    assert result.applied is True

    conn = connect(db_path)
    row = get_file_row(conn, "a.txt")
    conn.close()
    assert row.reference_sha256 == result.new_hash
    assert row.candidate_sha256 is None


def test_accept_rejects_unindexed_path(tmp_path):
    root, db_path = _make_storage(tmp_path)
    with pytest.raises(UsageError):
        cmd_accept(root, db_path, "nonexistent.txt", apply=False)


def test_accept_rejects_symlink(tmp_path):
    root, db_path = _make_storage(tmp_path)
    target = root / "real.txt"
    target.write_text("x")
    link = root / "link.txt"
    link.symlink_to(target)
    run_index(root, db_path, apply=True)

    with pytest.raises(UsageError):
        cmd_accept(root, db_path, "link.txt", apply=False)
