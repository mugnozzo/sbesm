"""Phase 7.3: streaming-hash and scale sanity checks.

True peak-memory measurement is fragile and platform-dependent for a unit
test, so "bounded memory" is verified the practical way: proving hash_file
reads and hashes in capped-size chunks (never materializing a whole large
file in one read), which is what actually keeps its memory footprint
constant regardless of file size.
"""

import hashlib
import os
from unittest import mock

from sbesm.db import connect
from sbesm.hashing import hash_file
from sbesm.indexing import Classification, run_index
from sbesm.init_cmd import cmd_init
from sbesm.migrations import MIGRATIONS, apply_migrations
from sbesm.verify import VerifyStatus, run_verify


def test_hash_file_reads_in_bounded_chunks_not_one_big_read(tmp_path):
    path = tmp_path / "big.bin"
    content = os.urandom(3 * 1024 * 1024)  # 3 MiB
    path.write_bytes(content)
    chunk_size = 64 * 1024

    update_calls: list[int] = []
    real_sha256 = hashlib.sha256

    class CountingHasher:
        def __init__(self) -> None:
            self._h = real_sha256()

        def update(self, chunk: bytes) -> None:
            update_calls.append(len(chunk))
            self._h.update(chunk)

        def hexdigest(self) -> str:
            return self._h.hexdigest()

    with mock.patch("sbesm.hashing.hashlib.sha256", return_value=CountingHasher()):
        digest = hash_file(path, chunk_size=chunk_size)

    assert digest == real_sha256(content).hexdigest()
    assert len(update_calls) > 10  # many chunked reads, not a single whole-file read
    assert all(size <= chunk_size for size in update_calls)
    assert sum(update_calls) == len(content)


def _make_storage(tmp_path, name):
    root = tmp_path / name
    cmd_init(root, name=name)
    return root


def test_indexes_many_small_files_correctly(tmp_path):
    root = _make_storage(tmp_path, "root")
    for i in range(300):
        (root / f"file_{i:04d}.txt").write_text(f"content {i}")

    db_path = root / ".sbesm" / "index.sqlite"
    result = run_index(root, db_path, apply=True)
    assert len(result.entries) == 300
    assert all(e.classification == Classification.NEW for e in result.entries)

    verify_result = run_verify(root, db_path)
    assert len(verify_result.entries) == 300
    assert all(e.status == VerifyStatus.OK for e in verify_result.entries)

    conn = connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    assert count == 300


def test_indexes_few_large_files_correctly(tmp_path):
    root = _make_storage(tmp_path, "root")
    contents = [os.urandom(5 * 1024 * 1024) for _ in range(2)]  # 5 MiB each
    for i, content in enumerate(contents):
        (root / f"large_{i}.bin").write_bytes(content)

    db_path = root / ".sbesm" / "index.sqlite"
    result = run_index(root, db_path, apply=True)
    assert len(result.entries) == 2
    assert all(e.classification == Classification.NEW for e in result.entries)

    conn = connect(db_path)
    rows = conn.execute("SELECT path, reference_sha256 FROM files ORDER BY path").fetchall()
    conn.close()
    for (path_name, ref_hash), content in zip(rows, contents, strict=True):
        assert ref_hash == hashlib.sha256(content).hexdigest()


def test_many_small_files_scan_is_deterministic_and_sorted(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    sbesm_dir = root / ".sbesm"
    sbesm_dir.mkdir()
    conn = connect(sbesm_dir / "index.sqlite")
    apply_migrations(conn, MIGRATIONS)
    conn.close()

    for i in range(200):
        (root / f"{i:04d}.txt").write_text("x")

    from sbesm.scanner import walk_root

    first = [e.relative_path for e in walk_root(root)]
    second = [e.relative_path for e in walk_root(root)]
    assert first == second == sorted(first)
    assert len(first) == 200
