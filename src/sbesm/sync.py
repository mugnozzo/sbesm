import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sbesm.diff import DiffEntry, DiffStatus, run_diff
from sbesm.errors import IOFailureError, StorageUnavailableError, UsageError
from sbesm.fsident import is_mounted_and_responsive
from sbesm.indexing import run_index
from sbesm.scope import ResolvedSide

_CONFLICT_STATUSES = {DiffStatus.DIFFERENT, DiffStatus.TYPE_MISMATCH}


def build_rsync_command(
    source: Path, dest: Path, *, dry_run: bool, delete: bool = False, update: bool = False
) -> list[str]:
    cmd = [
        "rsync",
        "-a",
        "--itemize-changes",
        "--partial-dir=.rsync-partial",
        "--info=progress2",
        "--exclude=/.sbesm/",
    ]
    if dry_run:
        cmd.append("--dry-run")
    if update:
        cmd.append("--update")
    if delete:
        cmd.append("--delete")

    # trailing slash on a directory source means "sync its contents into dest",
    # not "nest the directory one level deeper" -- matches the spec's baseline
    # `rsync -a ... SOURCE/ DEST/` convention. A file selector is copied as-is.
    if source.is_dir():
        cmd.append(f"{source}/")
        cmd.append(f"{dest}/")
    else:
        cmd.append(str(source))
        cmd.append(str(dest))
    return cmd


def _validate_no_root_overlap(source_root: Path, dest_root: Path) -> None:
    source_resolved = source_root.resolve()
    dest_resolved = dest_root.resolve()
    if (
        source_resolved == dest_resolved
        or source_resolved in dest_resolved.parents
        or dest_resolved in source_resolved.parents
    ):
        raise UsageError(
            f"source and destination roots overlap: {source_resolved} vs {dest_resolved}"
        )


def _top_level_names(root: Path) -> set[str]:
    return {p.name for p in root.iterdir() if p.name != ".sbesm"}


def _detect_conflicts(source_root: Path, dest_root: Path, selectors: list[str]) -> list[DiffEntry]:
    return run_diff(ResolvedSide(source_root, selectors), ResolvedSide(dest_root, selectors))


@dataclass
class SelectorSyncOutcome:
    selector: str
    skipped_reason: str | None = None
    rsync_returncode: int | None = None
    rsync_stdout: str = ""


@dataclass
class SyncResult:
    selectors: list[str]
    conflicts: list[DiffEntry]
    dest_only: list[DiffEntry]
    applied: bool
    outcomes: list[SelectorSyncOutcome] = field(default_factory=list)
    log_path: Path | None = None


def _write_sync_log(
    sbesm_dir: Path,
    apply: bool,
    selectors: list[str],
    conflicts: list[DiffEntry],
    dest_only: list[DiffEntry],
    outcomes: list[SelectorSyncOutcome],
    interrupted: bool = False,
) -> Path:
    logs_dir = sbesm_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = logs_dir / f"sync-{timestamp}.log"

    mode_label = "APPLY" if apply else "DRY RUN"
    if interrupted:
        mode_label += " (INTERRUPTED)"

    lines = [
        f"sbesm sync [{mode_label}]",
        f"selectors: {selectors}",
        f"conflicts: {[e.relative_path for e in conflicts]}",
        f"destination-only: {[e.relative_path for e in dest_only]}",
    ]
    for outcome in outcomes:
        if outcome.skipped_reason:
            lines.append(f"  {outcome.selector}: SKIPPED ({outcome.skipped_reason})")
        else:
            lines.append(f"  {outcome.selector}: rsync exit={outcome.rsync_returncode}")

    log_path.write_text("\n".join(lines) + "\n")
    return log_path


def _post_sync_reindex(dest_root: Path, outcomes: list[SelectorSyncOutcome]) -> None:
    dest_db_path = dest_root / ".sbesm" / "index.sqlite"
    for outcome in outcomes:
        if outcome.skipped_reason is None and outcome.rsync_returncode == 0:
            run_index(dest_root, dest_db_path, scope=[outcome.selector], apply=True)


def run_sync(
    source_root: Path,
    dest_root: Path,
    selectors: list[str] | None,
    *,
    delete: bool = False,
    update: bool = False,
    overwrite_conflicts: bool = False,
    apply: bool = False,
) -> SyncResult:
    _validate_no_root_overlap(source_root, dest_root)

    names = (
        sorted(_top_level_names(source_root) | _top_level_names(dest_root))
        if selectors is None
        else selectors
    )

    diff_entries = _detect_conflicts(source_root, dest_root, names)
    conflicts = [e for e in diff_entries if e.status in _CONFLICT_STATUSES]
    dest_only = [e for e in diff_entries if e.status == DiffStatus.DEST_ONLY]

    if apply and conflicts and not overwrite_conflicts:
        raise UsageError(
            f"{len(conflicts)} content conflict(s) detected; pass --overwrite-conflicts "
            f"to apply anyway, or resolve them first. Conflicting paths: "
            f"{[e.relative_path for e in conflicts][:10]}"
        )

    if apply:
        for root in (source_root, dest_root):
            if not is_mounted_and_responsive(root):
                raise StorageUnavailableError(f"{root} is not mounted or not responding")

    outcomes: list[SelectorSyncOutcome] = []
    try:
        for selector in names:
            source_path = source_root / selector
            if not source_path.exists():
                # never risk deleting dest's copy just because source lacks it
                # right now (invariant: a missing source category/path never
                # triggers destination deletion).
                outcomes.append(
                    SelectorSyncOutcome(
                        selector, skipped_reason="missing on source; destination preserved untouched"
                    )
                )
                continue

            dest_path = dest_root / selector
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = build_rsync_command(source_path, dest_path, dry_run=not apply, delete=delete, update=update)
            try:
                proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
            except FileNotFoundError as exc:
                raise IOFailureError("rsync binary not found on PATH") from exc
            outcomes.append(
                SelectorSyncOutcome(selector, rsync_returncode=proc.returncode, rsync_stdout=proc.stdout)
            )
    except KeyboardInterrupt:
        _write_sync_log(dest_root / ".sbesm", apply, names, conflicts, dest_only, outcomes, interrupted=True)
        raise

    log_path = _write_sync_log(dest_root / ".sbesm", apply, names, conflicts, dest_only, outcomes)

    if apply:
        _post_sync_reindex(dest_root, outcomes)

    return SyncResult(
        selectors=names,
        conflicts=conflicts,
        dest_only=dest_only,
        applied=apply,
        outcomes=outcomes,
        log_path=log_path,
    )
