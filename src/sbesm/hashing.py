import hashlib
import os
from collections.abc import Callable
from pathlib import Path

from sbesm.errors import UsageError

SUPPORTED_ALGORITHMS = {"sha256"}


class NotHashableError(Exception):
    pass


class UnstableFileError(Exception):
    pass


def validate_hashing_algorithm(algorithm: str) -> None:
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise UsageError(
            f"unsupported hashing algorithm {algorithm!r} in v1 "
            f"(only {sorted(SUPPORTED_ALGORITHMS)} supported)"
        )


def hash_file(path: Path, chunk_size: int = 1 << 20) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_file_stable(
    path: Path,
    retries: int = 2,
    chunk_size: int = 1 << 20,
    stat_func: Callable[[Path], os.stat_result] = os.lstat,
) -> str:
    path = Path(path)
    if path.is_symlink():
        raise NotHashableError(f"{path} is a symlink and must not be hashed")

    for _attempt in range(retries + 1):
        before = stat_func(path)
        digest = hash_file(path, chunk_size=chunk_size)
        after = stat_func(path)
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
            return digest

    raise UnstableFileError(
        f"{path} metadata changed during hashing after {retries} retries"
    )
