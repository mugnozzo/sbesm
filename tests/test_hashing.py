import hashlib

import pytest

from sbesm.errors import UsageError
from sbesm.hashing import (
    NotHashableError,
    UnstableFileError,
    hash_file,
    hash_file_stable,
    validate_hashing_algorithm,
)

# --- 2.3.1 chunked hasher ----------------------------------------------------


@pytest.mark.parametrize("content", [b"", b"x", b"a" * 10, b"abcdefgh" * 3])
def test_hash_file_matches_hashlib_across_chunk_boundaries(tmp_path, content):
    path = tmp_path / "f.bin"
    path.write_bytes(content)
    assert hash_file(path, chunk_size=4) == hashlib.sha256(content).hexdigest()


# --- 2.3.2 stability wrapper -------------------------------------------------


def test_hash_file_stable_returns_digest_for_untouched_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello")
    assert hash_file_stable(path) == hashlib.sha256(b"hello").hexdigest()


def test_hash_file_stable_raises_when_metadata_keeps_changing(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello")

    class FakeStat:
        def __init__(self, size: int) -> None:
            self.st_size = size
            self.st_mtime_ns = 0

    counter = iter(range(100))

    def flaky_stat(_path: object) -> FakeStat:
        return FakeStat(size=next(counter))

    with pytest.raises(UnstableFileError):
        hash_file_stable(path, retries=2, stat_func=flaky_stat)


# --- 2.3.3 never-follow-symlink guard ---------------------------------------


def test_hash_file_stable_refuses_symlink(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("data")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(NotHashableError):
        hash_file_stable(link)


# --- 2.3.4 algorithm validation ----------------------------------------------


def test_validate_hashing_algorithm_accepts_sha256():
    validate_hashing_algorithm("sha256")  # should not raise


def test_validate_hashing_algorithm_rejects_unsupported():
    with pytest.raises(UsageError):
        validate_hashing_algorithm("blake3")
