import sqlite3
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from sbesm.db import (
    FileRow,
    connect,
    finish_run,
    list_file_rows,
    start_run,
    storage_write_lock,
    upsert_file_row,
)
from sbesm.hashing import hash_file_stable
from sbesm.scanner import ScannedEntry, walk_root
from sbesm.selectors import normalize_selection


class Classification(str, Enum):
    NEW = "new"
    UNCHANGED = "unchanged"
    CHANGED_SAME_HASH = "changed-same-hash"
    CHANGED_CONFLICT = "changed-conflict"
    CHANGED_UNKNOWN = "changed-unknown"  # metadata changed, but hashing was skipped
    MISSING = "missing"
    UNREADABLE = "unreadable"


@dataclass
class ClassifiedEntry:
    relative_path: str
    classification: Classification
    scanned: ScannedEntry | None
    existing: FileRow | None
    computed_hash: str | None = None


def classify(
    scanned: ScannedEntry | None,
    existing: FileRow | None,
    *,
    allow_hashing: bool = True,
    force_rehash: bool = False,
) -> ClassifiedEntry:
    if scanned is None:
        assert existing is not None, "classify() needs scanned and/or existing data"
        return ClassifiedEntry(existing.path, Classification.MISSING, None, existing)

    relative_path = scanned.relative_path

    if scanned.kind == "unreadable":
        return ClassifiedEntry(relative_path, Classification.UNREADABLE, scanned, existing)

    if scanned.kind == "symlink":
        if existing is None or existing.kind != "symlink":
            return ClassifiedEntry(relative_path, Classification.NEW, scanned, existing)
        if existing.symlink_target == scanned.symlink_target:
            return ClassifiedEntry(relative_path, Classification.UNCHANGED, scanned, existing)
        return ClassifiedEntry(relative_path, Classification.CHANGED_CONFLICT, scanned, existing)

    # scanned.kind == "regular"
    is_new = existing is None or existing.kind != "regular" or existing.reference_sha256 is None
    metadata_unchanged = (
        not is_new
        and existing is not None
        and existing.size == scanned.size
        and existing.mtime_ns == scanned.mtime_ns
    )

    if metadata_unchanged and not force_rehash:
        return ClassifiedEntry(relative_path, Classification.UNCHANGED, scanned, existing)

    if not allow_hashing:
        if is_new:
            return ClassifiedEntry(relative_path, Classification.NEW, scanned, existing)
        return ClassifiedEntry(relative_path, Classification.CHANGED_UNKNOWN, scanned, existing)

    computed_hash = hash_file_stable(scanned.absolute_path)
    if is_new:
        return ClassifiedEntry(relative_path, Classification.NEW, scanned, existing, computed_hash)
    assert existing is not None
    if computed_hash == existing.reference_sha256:
        return ClassifiedEntry(
            relative_path, Classification.CHANGED_SAME_HASH, scanned, existing, computed_hash
        )
    return ClassifiedEntry(
        relative_path, Classification.CHANGED_CONFLICT, scanned, existing, computed_hash
    )


_NOTEWORTHY = {
    Classification.CHANGED_CONFLICT,
    Classification.CHANGED_UNKNOWN,
    Classification.MISSING,
    Classification.UNREADABLE,
}


def has_findings(results: list[ClassifiedEntry]) -> bool:
    return any(r.classification in _NOTEWORTHY for r in results)


def render_preview(results: list[ClassifiedEntry]) -> str:
    counts = Counter(r.classification for r in results)
    lines = [f"  {c.value}: {counts[c]}" for c in Classification if counts[c]]
    if not lines:
        lines = ["  (no files found in scope)"]
    changed = [r.relative_path for r in results if r.classification != Classification.UNCHANGED]
    if changed:
        lines.append("  changed paths:")
        lines.extend(f"    {p}" for p in changed)
    return "\n".join(lines)


def _apply_classified_entries(
    conn: sqlite3.Connection, results: list[ClassifiedEntry]
) -> None:
    now = datetime.now(UTC).isoformat()

    for entry in results:
        if entry.classification == Classification.MISSING:
            assert entry.existing is not None
            row = replace(entry.existing, state="missing", last_seen_at=now)
            upsert_file_row(conn, row)
            continue

        scanned = entry.scanned
        assert scanned is not None

        if entry.classification == Classification.UNREADABLE:
            existing = entry.existing
            row = FileRow(
                path=entry.relative_path,
                kind=existing.kind if existing else "unreadable",
                size=None,
                mtime_ns=None,
                reference_sha256=existing.reference_sha256 if existing else None,
                reference_size=existing.reference_size if existing else None,
                reference_mtime_ns=existing.reference_mtime_ns if existing else None,
                hashed_at=existing.hashed_at if existing else None,
                last_seen_at=now,
                state="unreadable",
                candidate_sha256=None,
                symlink_target=existing.symlink_target if existing else None,
            )
            upsert_file_row(conn, row)
            continue

        if entry.classification == Classification.NEW:
            is_regular = scanned.kind == "regular"
            has_hash = is_regular and entry.computed_hash is not None
            row = FileRow(
                path=entry.relative_path,
                kind=scanned.kind,
                size=scanned.size,
                mtime_ns=scanned.mtime_ns,
                reference_sha256=entry.computed_hash if has_hash else None,
                reference_size=scanned.size if has_hash else None,
                reference_mtime_ns=scanned.mtime_ns if has_hash else None,
                hashed_at=now if has_hash else None,
                last_seen_at=now,
                state="indexed" if (has_hash or scanned.kind == "symlink") else "unindexed",
                candidate_sha256=None,
                symlink_target=scanned.symlink_target,
            )
            upsert_file_row(conn, row)
            continue

        existing = entry.existing
        assert existing is not None

        if entry.classification == Classification.UNCHANGED:
            row = replace(
                existing, size=scanned.size, mtime_ns=scanned.mtime_ns, last_seen_at=now, state="indexed"
            )
        elif entry.classification == Classification.CHANGED_SAME_HASH:
            row = replace(
                existing,
                size=scanned.size,
                mtime_ns=scanned.mtime_ns,
                last_seen_at=now,
                state="indexed",
                candidate_sha256=None,
            )
        elif entry.classification == Classification.CHANGED_CONFLICT:
            row = replace(
                existing,
                size=scanned.size,
                mtime_ns=scanned.mtime_ns,
                last_seen_at=now,
                state="changed",
                candidate_sha256=entry.computed_hash,
                symlink_target=scanned.symlink_target
                if scanned.kind == "symlink"
                else existing.symlink_target,
            )
        elif entry.classification == Classification.CHANGED_UNKNOWN:
            row = replace(
                existing, size=scanned.size, mtime_ns=scanned.mtime_ns, last_seen_at=now, state="changed"
            )
        else:  # pragma: no cover - exhaustive above
            raise AssertionError(f"unexpected classification {entry.classification}")

        upsert_file_row(conn, row)


def _write_run_log(
    sbesm_dir: Path, plan_only: bool, apply: bool, results: list[ClassifiedEntry]
) -> Path:
    logs_dir = sbesm_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs_dir / f"index-{timestamp}.log"
    mode_label = "APPLY" if apply else "DRY RUN"
    if plan_only:
        mode_label += " (plan-only)"
    log_path.write_text(f"sbesm index [{mode_label}]\n{render_preview(results)}\n")
    return log_path


@dataclass
class IndexResult:
    entries: list[ClassifiedEntry]
    log_path: Path


def run_index(
    root: Path,
    db_path: Path,
    *,
    scope: list[str] | None = None,
    plan_only: bool = False,
    rehash: bool = False,
    apply: bool = False,
    exclude_patterns: list[str] | None = None,
) -> IndexResult:
    conn = connect(db_path)
    run_id: int | None = None
    try:
        scanned_by_path = {e.relative_path: e for e in walk_root(root, scope, exclude_patterns)}
        existing_by_path = {r.path: r for r in list_file_rows(conn)}

        if scope is not None:
            normalized_scope = normalize_selection(scope).paths
            existing_by_path = {
                path: row
                for path, row in existing_by_path.items()
                if any(path == s or path.startswith(s + "/") for s in normalized_scope)
            }

        all_paths = sorted(set(scanned_by_path) | set(existing_by_path))
        results = [
            classify(
                scanned_by_path.get(path),
                existing_by_path.get(path),
                allow_hashing=not plan_only,
                force_rehash=rehash,
            )
            for path in all_paths
        ]

        if apply:
            with storage_write_lock(db_path.parent):
                run_id = start_run(conn, "index")
                try:
                    _apply_classified_entries(conn, results)
                    conn.commit()
                except KeyboardInterrupt:
                    conn.rollback()
                    finish_run(conn, run_id, "interrupted")
                    raise
                except BaseException:
                    conn.rollback()
                    finish_run(conn, run_id, "failed")
                    raise
                else:
                    finish_run(conn, run_id, "success")

        log_path = _write_run_log(db_path.parent, plan_only, apply, results)
        return IndexResult(entries=results, log_path=log_path)
    finally:
        conn.close()
