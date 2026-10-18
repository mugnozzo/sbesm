from sbesm import cli
from sbesm.config import StorageConfig
from sbesm.db import connect
from sbesm.indexing import run_index
from sbesm.init_cmd import cmd_init
from sbesm.migrations import MIGRATIONS, apply_migrations
from sbesm.status import compute_category_presence, compute_counts, last_run_summary


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


# --- 2.6.1 category presence reporting --------------------------------------


def test_category_presence_distinguishes_expected_present_indexed(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "photos").mkdir()  # present, not expected, not indexed
    (root / "documents").mkdir()
    (root / "documents" / "a.txt").write_text("x")

    config = StorageConfig(id="x", name="x", known_categories=["documents", "videos"])
    run_index(root, db_path, apply=True)  # indexes documents/a.txt only

    conn = connect(db_path)
    presence = compute_category_presence(root, config, conn)
    conn.close()

    assert presence.expected == {"documents", "videos"}
    assert presence.present == {"photos", "documents"}
    assert presence.indexed == {"documents"}


# --- 2.6.2 counts/bytes aggregation ------------------------------------------


def test_counts_and_bytes_match_fixture(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("hello")  # 5 bytes
    (root / "b.txt").write_text("worldly")  # 7 bytes
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    counts, total_bytes = compute_counts(conn)
    conn.close()

    assert counts["indexed"] == 2
    assert total_bytes == 12


def test_counts_scoped_by_folder(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "documents").mkdir()
    (root / "documents" / "a.txt").write_text("hello")
    (root / "photos").mkdir()
    (root / "photos" / "b.txt").write_text("worldly")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    counts, total_bytes = compute_counts(conn, scope="documents")
    conn.close()

    assert counts["indexed"] == 1
    assert total_bytes == 5


# --- 2.6.3 last-run summary tolerates verify never having run ---------------


def test_last_run_summary_tolerates_missing_verify(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("x")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    summary = last_run_summary(conn)
    conn.close()

    assert summary["index"] is not None
    assert summary["index"].outcome == "success"
    assert summary["verify"] is None


# --- 2.6.4 CLI wiring + disclaimer -------------------------------------------


def test_status_cli_prints_disclaimer_and_counts(tmp_path, capsys):
    root = tmp_path / "root"
    cmd_init(root, name="demo")
    (root / "documents").mkdir()
    (root / "documents" / "a.txt").write_text("hello")

    assert cli.main(["index", str(root), "--apply"]) in (0, 1)
    code = cli.main(["status", str(root)])
    out = capsys.readouterr().out

    assert code == 0
    assert "demo" in out
    assert "stored checksums are references" in out
    assert "Last index run" in out
    assert "Last verify run: never run" in out
