from sbesm.db import connect
from sbesm.duplicates import find_duplicates, verify_duplicate_groups
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


# --- 3.3 duplicates: index-based grouping -----------------------------------


def test_finds_duplicate_group_by_same_content(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("same content")
    (root / "b.txt").write_text("same content")
    (root / "c.txt").write_text("different")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    groups = find_duplicates(conn)
    conn.close()

    assert len(groups) == 1
    assert groups[0].paths == ["a.txt", "b.txt"]


def test_min_size_filters_small_groups(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("x")  # 1 byte
    (root / "b.txt").write_text("x")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    groups = find_duplicates(conn, min_size=10)
    conn.close()
    assert groups == []


def test_folder_scope_restricts_grouping(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "documents").mkdir()
    (root / "documents" / "a.txt").write_text("same")
    (root / "photos").mkdir()
    (root / "photos" / "b.txt").write_text("same")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    all_groups = find_duplicates(conn)
    scoped_groups = find_duplicates(conn, scope="documents")
    conn.close()

    assert len(all_groups) == 1
    assert scoped_groups == []  # only one of the two duplicate paths lies in scope


def test_symlinks_excluded_from_duplicate_groups(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("same")
    (root / "b.txt").write_text("same")
    link = root / "link_to_a"
    link.symlink_to(root / "a.txt")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    groups = find_duplicates(conn)
    conn.close()

    assert len(groups) == 1
    assert "link_to_a" not in groups[0].paths


# --- 3.4 duplicates --verify: separates verified from stale-index ----------


def test_verify_duplicate_groups_detects_stale_false_positive(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("same content")
    (root / "b.txt").write_text("same content")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    groups = find_duplicates(conn)
    conn.close()
    assert len(groups) == 1

    # silently corrupt b.txt on disk without re-indexing, so the index's claim
    # that it's still a duplicate of a.txt is now stale
    (root / "b.txt").write_text("totally different now")

    verified = verify_duplicate_groups(root, groups)
    assert len(verified) == 1
    assert verified[0].verified_paths == ["a.txt"]
    assert verified[0].stale_paths == ["b.txt"]


def test_verify_duplicate_groups_confirms_real_duplicates(tmp_path):
    root, db_path = _make_storage(tmp_path)
    (root / "a.txt").write_text("same content")
    (root / "b.txt").write_text("same content")
    run_index(root, db_path, apply=True)

    conn = connect(db_path)
    groups = find_duplicates(conn)
    conn.close()

    verified = verify_duplicate_groups(root, groups)
    assert sorted(verified[0].verified_paths) == ["a.txt", "b.txt"]
    assert verified[0].stale_paths == []
