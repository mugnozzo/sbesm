from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from sbesm.db import FileRow, connect, finish_run, list_file_rows, start_run
from sbesm.hashing import NotHashableError, UnstableFileError, hash_file_stable
from sbesm.scanner import ScannedEntry, walk_root
from sbesm.selectors import normalize_selection


class VerifyStatus(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"
    MISSING = "missing"
    UNINDEXED = "unindexed"
    UNREADABLE = "unreadable"
    UNSTABLE = "unstable"
    SYMLINK = "symlink"


@dataclass
class VerifiedEntry:
    relative_path: str
    status: VerifyStatus
    fresh_hash: str | None = None
    reference_hash: str | None = None


def _verify_one(scanned: ScannedEntry | None, existing: FileRow | None) -> VerifiedEntry:
    if scanned is None:
        assert existing is not None
        return VerifiedEntry(existing.path, VerifyStatus.MISSING, reference_hash=existing.reference_sha256)

    relative_path = scanned.relative_path

    if scanned.kind == "unreadable":
        return VerifiedEntry(
            relative_path,
            VerifyStatus.UNREADABLE,
            reference_hash=existing.reference_sha256 if existing else None,
        )

    if scanned.kind == "symlink":
        return VerifiedEntry(relative_path, VerifyStatus.SYMLINK)

    if existing is None or existing.reference_sha256 is None:
        return VerifiedEntry(relative_path, VerifyStatus.UNINDEXED)

    try:
        fresh_hash = hash_file_stable(scanned.absolute_path)
    except UnstableFileError:
        return VerifiedEntry(
            relative_path, VerifyStatus.UNSTABLE, reference_hash=existing.reference_sha256
        )
    except (OSError, NotHashableError):
        return VerifiedEntry(
            relative_path, VerifyStatus.UNREADABLE, reference_hash=existing.reference_sha256
        )

    if fresh_hash == existing.reference_sha256:
        return VerifiedEntry(relative_path, VerifyStatus.OK, fresh_hash, existing.reference_sha256)
    return VerifiedEntry(relative_path, VerifyStatus.MISMATCH, fresh_hash, existing.reference_sha256)


_FINDINGS_STATUSES = {
    VerifyStatus.MISMATCH,
    VerifyStatus.MISSING,
    VerifyStatus.UNINDEXED,
    VerifyStatus.UNREADABLE,
    VerifyStatus.UNSTABLE,
}


def has_verify_findings(results: list[VerifiedEntry]) -> bool:
    return any(r.status in _FINDINGS_STATUSES for r in results)


def render_verify_summary(results: list[VerifiedEntry]) -> str:
    counts = Counter(r.status for r in results)
    lines = [f"  {s.value}: {counts[s]}" for s in VerifyStatus if counts[s]]
    if not lines:
        lines = ["  (no files found in scope)"]
    problems = [r.relative_path for r in results if r.status in _FINDINGS_STATUSES][:10]
    if problems:
        lines.append("  sample anomalies:")
        lines.extend(f"    {p}" for p in problems)
    return "\n".join(lines)


def _write_verify_log(sbesm_dir: Path, results: list[VerifiedEntry]) -> Path:
    logs_dir = sbesm_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs_dir / f"verify-{timestamp}.log"
    log_path.write_text(f"sbesm verify\n{render_verify_summary(results)}\n")
    return log_path


@dataclass
class VerifyRunResult:
    entries: list[VerifiedEntry]
    log_path: Path


def run_verify(
    root: Path, db_path: Path, *, scope: list[str] | None = None
) -> VerifyRunResult:
    conn = connect(db_path)
    try:
        scanned_by_path = {e.relative_path: e for e in walk_root(root, scope)}
        existing_by_path = {r.path: r for r in list_file_rows(conn)}

        if scope is not None:
            normalized_scope = normalize_selection(scope).paths
            existing_by_path = {
                path: row
                for path, row in existing_by_path.items()
                if any(path == s or path.startswith(s + "/") for s in normalized_scope)
            }

        all_paths = sorted(set(scanned_by_path) | set(existing_by_path))

        run_id = start_run(conn, "verify")
        try:
            results = [
                _verify_one(scanned_by_path.get(path), existing_by_path.get(path))
                for path in all_paths
            ]
        except KeyboardInterrupt:
            finish_run(conn, run_id, "interrupted")
            raise
        except BaseException:
            finish_run(conn, run_id, "failed")
            raise
        else:
            finish_run(conn, run_id, "success")

        log_path = _write_verify_log(db_path.parent, results)
        return VerifyRunResult(entries=results, log_path=log_path)
    finally:
        conn.close()
