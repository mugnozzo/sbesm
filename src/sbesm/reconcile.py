import os
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from sbesm.config import read_storage_config
from sbesm.db import (
    FileRow,
    connect,
    get_file_row,
    list_file_rows,
    storage_write_lock,
    upsert_file_row,
)
from sbesm.errors import UsageError
from sbesm.fsident import detect_filesystem_type
from sbesm.hashing import NotHashableError, UnstableFileError, hash_file_stable
from sbesm.scanner import ScannedEntry, walk_root

MTIME_TOLERANCE_NS = {
    "ext4": 1_000_000,
    "btrfs": 1_000_000,
    "xfs": 1_000_000,
    "vfat": 2_000_000_000,
    "exfat": 2_000_000_000,
    "msdos": 2_000_000_000,
}
DEFAULT_TOLERANCE_NS = 2_000_000_000  # unknown/coarse/FUSE filesystems

VALID_POLICIES = {"oldest", "newest", "source"}


def get_mtime_tolerance_ns(root: Path) -> int:
    fstype = detect_filesystem_type(root)
    if fstype is None:
        return DEFAULT_TOLERANCE_NS
    return MTIME_TOLERANCE_NS.get(fstype, DEFAULT_TOLERANCE_NS)


def _effective_tolerance_ns(root_a: Path, root_b: Path) -> int:
    config_a = read_storage_config(root_a / ".sbesm" / "config.toml")
    config_b = read_storage_config(root_b / ".sbesm" / "config.toml")
    tol_a = config_a.mtime_tolerance_ns if config_a.mtime_tolerance_ns is not None else get_mtime_tolerance_ns(root_a)
    tol_b = config_b.mtime_tolerance_ns if config_b.mtime_tolerance_ns is not None else get_mtime_tolerance_ns(root_b)
    return max(tol_a, tol_b)


class ReconcileAction(str, Enum):
    RECONCILED = "reconciled"
    ALREADY_ALIGNED = "already-aligned"
    SKIPPED_MISMATCH = "mismatch"
    SKIPPED_UNREADABLE = "unreadable"
    SKIPPED_MISSING = "missing"
    SKIPPED_SYMLINK = "symlink"
    SKIPPED_UNKNOWN_HASH = "unknown-hash"


@dataclass
class ReconcileEntry:
    relative_path: str
    action: ReconcileAction
    a_mtime_ns: int | None = None
    b_mtime_ns: int | None = None
    target_mtime_ns: int | None = None
    updated_side: str | None = None  # "a" | "b"


def _resolve_hash(row: FileRow | None, scanned: ScannedEntry) -> str | None:
    if scanned.kind != "regular":
        return None
    if (
        row is not None
        and row.reference_sha256 is not None
        and row.state == "indexed"
        and row.size == scanned.size
        and row.mtime_ns == scanned.mtime_ns
    ):
        return row.reference_sha256
    try:
        return hash_file_stable(scanned.absolute_path)
    except (OSError, NotHashableError, UnstableFileError):
        return None


def _classify_pair(
    relative_path: str,
    a_scanned: ScannedEntry | None,
    b_scanned: ScannedEntry | None,
    a_row: FileRow | None,
    b_row: FileRow | None,
    policy: str,
    tolerance_ns: int,
) -> ReconcileEntry:
    if a_scanned is None or b_scanned is None:
        return ReconcileEntry(relative_path, ReconcileAction.SKIPPED_MISSING)

    if a_scanned.kind == "symlink" or b_scanned.kind == "symlink":
        return ReconcileEntry(relative_path, ReconcileAction.SKIPPED_SYMLINK)

    if a_scanned.kind != "regular" or b_scanned.kind != "regular":
        return ReconcileEntry(relative_path, ReconcileAction.SKIPPED_UNREADABLE)

    a_hash = _resolve_hash(a_row, a_scanned)
    b_hash = _resolve_hash(b_row, b_scanned)
    if a_hash is None or b_hash is None:
        return ReconcileEntry(relative_path, ReconcileAction.SKIPPED_UNKNOWN_HASH)
    if a_hash != b_hash:
        return ReconcileEntry(relative_path, ReconcileAction.SKIPPED_MISMATCH)

    a_mtime = a_scanned.mtime_ns
    b_mtime = b_scanned.mtime_ns
    assert a_mtime is not None and b_mtime is not None

    if abs(a_mtime - b_mtime) <= tolerance_ns:
        return ReconcileEntry(relative_path, ReconcileAction.ALREADY_ALIGNED, a_mtime, b_mtime)

    if policy == "oldest":
        target = min(a_mtime, b_mtime)
        updated_side = "a" if a_mtime > b_mtime else "b"
    elif policy == "newest":
        target = max(a_mtime, b_mtime)
        updated_side = "a" if a_mtime < b_mtime else "b"
    else:  # "source"
        target = a_mtime
        updated_side = "b"

    return ReconcileEntry(relative_path, ReconcileAction.RECONCILED, a_mtime, b_mtime, target, updated_side)


def _apply_mtime(path: Path, new_mtime_ns: int) -> None:
    # ctime can't be set directly (it's maintained automatically by the OS on
    # any inode metadata change, utime() included); atime is preserved as-is.
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, new_mtime_ns))


def _refresh_mtime_in_index(db_path: Path, relative_path: str, new_mtime_ns: int) -> None:
    conn = connect(db_path)
    try:
        row = get_file_row(conn, relative_path)
        if row is None:
            return
        updated = replace(
            row,
            mtime_ns=new_mtime_ns,
            reference_mtime_ns=new_mtime_ns if row.reference_sha256 is not None else row.reference_mtime_ns,
            last_seen_at=datetime.now(UTC).isoformat(),
        )
        upsert_file_row(conn, updated)
        conn.commit()
    finally:
        conn.close()


_FINDINGS_ACTIONS = {
    ReconcileAction.RECONCILED,
    ReconcileAction.SKIPPED_MISMATCH,
    ReconcileAction.SKIPPED_UNKNOWN_HASH,
}


def has_reconcile_findings(entries: list[ReconcileEntry]) -> bool:
    return any(e.action in _FINDINGS_ACTIONS for e in entries)


def render_reconcile_summary(entries: list[ReconcileEntry]) -> str:
    counts = Counter(e.action for e in entries)
    lines = [f"  {a.value}: {counts[a]}" for a in ReconcileAction if counts[a]]
    if not lines:
        lines = ["  (no files found in scope)"]
    reconciled = [e.relative_path for e in entries if e.action == ReconcileAction.RECONCILED][:10]
    if reconciled:
        lines.append("  reconciled paths:")
        lines.extend(f"    {p}" for p in reconciled)
    return "\n".join(lines)


def _write_reconcile_log(sbesm_dir: Path, apply: bool, policy: str, entries: list[ReconcileEntry]) -> Path:
    logs_dir = sbesm_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs_dir / f"reconcile-{timestamp}.log"
    mode_label = "APPLY" if apply else "DRY RUN"
    log_path.write_text(
        f"sbesm reconcile [{mode_label}] --mtime {policy}\n{render_reconcile_summary(entries)}\n"
    )
    return log_path


@dataclass
class ReconcileResult:
    entries: list[ReconcileEntry]
    log_path: Path


def run_reconcile(
    root_a: Path,
    root_b: Path,
    selectors: list[str] | None,
    *,
    policy: str = "oldest",
    apply: bool = False,
) -> ReconcileResult:
    if policy not in VALID_POLICIES:
        raise UsageError(f"unknown --mtime policy {policy!r}; expected one of {sorted(VALID_POLICIES)}")

    a_scanned = {e.relative_path: e for e in walk_root(root_a, selectors)}
    b_scanned = {e.relative_path: e for e in walk_root(root_b, selectors)}

    a_db_path = root_a / ".sbesm" / "index.sqlite"
    b_db_path = root_b / ".sbesm" / "index.sqlite"
    a_conn = connect(a_db_path)
    b_conn = connect(b_db_path)
    try:
        a_rows = {r.path: r for r in list_file_rows(a_conn)}
        b_rows = {r.path: r for r in list_file_rows(b_conn)}
    finally:
        a_conn.close()
        b_conn.close()

    tolerance_ns = _effective_tolerance_ns(root_a, root_b)

    all_paths = sorted(set(a_scanned) | set(b_scanned))
    entries = [
        _classify_pair(
            path, a_scanned.get(path), b_scanned.get(path), a_rows.get(path), b_rows.get(path), policy, tolerance_ns
        )
        for path in all_paths
    ]

    if apply:
        for entry in entries:
            if entry.action != ReconcileAction.RECONCILED:
                continue
            assert entry.target_mtime_ns is not None
            target_root = root_a if entry.updated_side == "a" else root_b
            target_db = a_db_path if entry.updated_side == "a" else b_db_path
            _apply_mtime(target_root / entry.relative_path, entry.target_mtime_ns)
            with storage_write_lock(target_db.parent):
                _refresh_mtime_in_index(target_db, entry.relative_path, entry.target_mtime_ns)

    log_path = _write_reconcile_log(b_db_path.parent, apply, policy, entries)
    return ReconcileResult(entries=entries, log_path=log_path)
