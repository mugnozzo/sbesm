import argparse
import sys
from pathlib import Path

from sbesm import exitcodes
from sbesm.accept_cmd import cmd_accept
from sbesm.config import read_storage_config
from sbesm.db import connect
from sbesm.diff import has_diff_findings, render_diff_report, run_diff
from sbesm.duplicates import find_duplicates, verify_duplicate_groups
from sbesm.errors import SbesmError
from sbesm.indexing import has_findings, render_preview, run_index
from sbesm.init_cmd import cmd_init
from sbesm.logging_setup import configure_logging
from sbesm.profiles import load_local_profiles
from sbesm.reconcile import has_reconcile_findings, render_reconcile_summary, run_reconcile
from sbesm.register_cmd import cmd_register
from sbesm.registry import (
    classify_registry,
    find_entries_by_root,
    find_entry_by_name_or_root,
    load_registry,
    remove_entry,
)
from sbesm.resolve import resolve_storage
from sbesm.scope import SelectionSpec, resolve_side
from sbesm.status import compute_category_presence, compute_counts, last_run_summary
from sbesm.sync import run_sync
from sbesm.uninit_cmd import cmd_uninit
from sbesm.verify import has_verify_findings, render_verify_summary, run_verify
from sbesm.xdg import config_home


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sbesm",
        description="Simple But Easy Synchronization Manager",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true")
    verbosity.add_argument("-q", "--quiet", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Initialize a new managed storage root"
    )
    init_parser.add_argument("root")
    init_parser.add_argument("--name")

    register_parser = subparsers.add_parser(
        "register", help="Register an already-initialized storage"
    )
    register_parser.add_argument("root")
    register_parser.add_argument("--name")

    unregister_parser = subparsers.add_parser(
        "unregister", help="Remove a storage from the local registry"
    )
    unregister_parser.add_argument("storage")
    unregister_parser.add_argument("-y", "--yes", action="store_true")

    uninit_parser = subparsers.add_parser(
        "uninit", help="Remove a storage's .sbesm directory (destructive)"
    )
    uninit_parser.add_argument("storage")
    uninit_parser.add_argument("--apply", action="store_true")
    uninit_parser.add_argument("-y", "--yes", action="store_true")

    subparsers.add_parser("storages", help="List registered storages")

    index_parser = subparsers.add_parser("index", help="Index files and detect changes")
    index_parser.add_argument("storage")
    index_parser.add_argument("--folder")
    index_parser.add_argument("--rehash", action="store_true")
    index_parser.add_argument("--plan-only", action="store_true")
    index_parser.add_argument("--apply", action="store_true")

    status_parser = subparsers.add_parser("status", help="Show storage status")
    status_parser.add_argument("storage")
    status_parser.add_argument("--folder")

    verify_parser = subparsers.add_parser("verify", help="Verify indexed files against their reference hashes")
    verify_parser.add_argument("storage")
    verify_parser.add_argument("--folder")

    accept_parser = subparsers.add_parser("accept", help="Accept a new reference hash for a file")
    accept_parser.add_argument("storage")
    accept_parser.add_argument("--path", required=True, dest="path")
    accept_parser.add_argument("--apply", action="store_true")

    duplicates_parser = subparsers.add_parser("duplicates", help="Report files sharing identical content")
    duplicates_parser.add_argument("storage")
    duplicates_parser.add_argument("--folder")
    duplicates_parser.add_argument("--min-size", type=int, default=0, dest="min_size")
    duplicates_parser.add_argument("--verify", action="store_true")

    diff_parser = subparsers.add_parser("diff", help="Compare two storages")
    diff_parser.add_argument("source")
    diff_parser.add_argument("dest")
    diff_parser.add_argument("--all", action="store_true")
    diff_parser.add_argument("--profile")
    diff_parser.add_argument("--folder", action="append", default=[], dest="folders")
    diff_parser.add_argument("--path", action="append", default=[], dest="paths")

    sync_parser = subparsers.add_parser("sync", help="One-way synchronization from SOURCE to DEST")
    sync_parser.add_argument("source")
    sync_parser.add_argument("dest")
    sync_parser.add_argument("--all", action="store_true")
    sync_parser.add_argument("--profile")
    sync_parser.add_argument("--folder", action="append", default=[], dest="folders")
    sync_parser.add_argument("--path", action="append", default=[], dest="paths")
    sync_parser.add_argument("--delete", action="store_true")
    sync_parser.add_argument("--update", action="store_true")
    sync_parser.add_argument("--overwrite-conflicts", action="store_true", dest="overwrite_conflicts")
    sync_parser.add_argument("--apply", action="store_true")

    reconcile_parser = subparsers.add_parser(
        "reconcile", help="Reconcile mtimes between two storages for proven-equal content"
    )
    reconcile_parser.add_argument("storage_a")
    reconcile_parser.add_argument("storage_b")
    reconcile_parser.add_argument("--all", action="store_true")
    reconcile_parser.add_argument("--profile")
    reconcile_parser.add_argument("--folder", action="append", default=[], dest="folders")
    reconcile_parser.add_argument("--path", action="append", default=[], dest="paths")
    reconcile_parser.add_argument(
        "--mtime", choices=["oldest", "newest", "source"], default="oldest", dest="mtime_policy"
    )
    reconcile_parser.add_argument("--apply", action="store_true")

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    config = cmd_init(Path(args.root), name=args.name)
    print(f"Initialized storage '{config.name}' (id={config.id}) at {args.root}")
    return exitcodes.SUCCESS


def _cmd_register(args: argparse.Namespace) -> int:
    entry = cmd_register(Path(args.root), name=args.name)
    print(f"Registered '{entry.name}' -> {entry.last_known_root} (id={entry.storage_id})")
    return exitcodes.SUCCESS


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False  # no real answer available -> never proceed destructively
    return answer in ("y", "yes")


def _cmd_unregister(args: argparse.Namespace) -> int:
    registry_path = config_home() / "registry.toml"
    entries = load_registry(registry_path)
    entry = find_entry_by_name_or_root(entries, args.storage)

    if not args.yes and not _confirm(
        f"Unregister '{entry.name}' (root={entry.last_known_root})? [y/N]: "
    ):
        print("Aborted.")
        return exitcodes.SUCCESS

    remove_entry(registry_path, entry.name)
    print(f"Unregistered '{entry.name}'.")
    return exitcodes.SUCCESS


def _cmd_uninit(args: argparse.Namespace) -> int:
    root = resolve_storage(args.storage)
    preview = cmd_uninit(root, apply=False)

    print(f"Would remove {preview.sbesm_dir} (storage_id={preview.storage_id}, "
          f"{preview.log_file_count} log file(s)). Your files are not touched.")

    if not args.apply:
        print("Pass --apply to actually remove it.")
        return exitcodes.SUCCESS

    if not args.yes and not _confirm(
        f"Delete {preview.sbesm_dir}? This removes all indexing history for "
        f"this storage. [y/N]: "
    ):
        print("Aborted.")
        return exitcodes.SUCCESS

    cmd_uninit(root, apply=True)
    print(f"Removed {preview.sbesm_dir}.")

    registry_path = config_home() / "registry.toml"
    entries = load_registry(registry_path)
    stale = find_entries_by_root(entries, root)
    for entry in stale:
        remove_entry(registry_path, entry.name)
    if stale:
        print(f"Also removed now-stale registry entry: {[e.name for e in stale]}")

    return exitcodes.SUCCESS


def _cmd_storages(args: argparse.Namespace) -> int:
    path = config_home() / "registry.toml"
    entries = load_registry(path)
    if not entries:
        print("No registered storages.")
        return exitcodes.SUCCESS

    availability = classify_registry(entries)
    for name in sorted(entries):
        entry = entries[name]
        print(f"{name}\t{availability[name]}\t{entry.last_known_root}\t(id={entry.storage_id})")
    return exitcodes.SUCCESS


def _cmd_index(args: argparse.Namespace) -> int:
    root = resolve_storage(args.storage)
    db_path = root / ".sbesm" / "index.sqlite"
    scope = [args.folder] if args.folder else None
    config = read_storage_config(root / ".sbesm" / "config.toml")

    result = run_index(
        root,
        db_path,
        scope=scope,
        plan_only=args.plan_only,
        rehash=args.rehash,
        apply=args.apply,
        exclude_patterns=config.exclude_patterns,
    )
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"index [{mode}]:")
    print(render_preview(result.entries))
    print(f"log: {result.log_path}")

    if has_findings(result.entries):
        return exitcodes.FINDINGS
    return exitcodes.SUCCESS


def _cmd_status(args: argparse.Namespace) -> int:
    root = resolve_storage(args.storage)
    sbesm_dir = root / ".sbesm"
    config = read_storage_config(sbesm_dir / "config.toml")
    conn = connect(sbesm_dir / "index.sqlite")
    try:
        presence = compute_category_presence(root, config, conn)
        counts, total_bytes = compute_counts(conn, scope=args.folder)
        runs = last_run_summary(conn)
    finally:
        conn.close()

    print(f"Storage: {config.name} (id={config.id})")
    print(f"Root: {root}")
    print(f"Categories expected: {sorted(presence.expected)}")
    print(f"Categories present:  {sorted(presence.present)}")
    print(f"Categories indexed:  {sorted(presence.indexed)}")
    for state, count in sorted(counts.items()):
        print(f"  {state}: {count}")
    print(f"Total indexed bytes: {total_bytes}")
    for command, info in runs.items():
        if info is None:
            print(f"Last {command} run: never run")
        else:
            print(f"Last {command} run: {info.started_at} -> outcome={info.outcome}")
    print("NOTE: stored checksums are references, not proof of current file integrity.")
    return exitcodes.SUCCESS


def _cmd_verify(args: argparse.Namespace) -> int:
    root = resolve_storage(args.storage)
    db_path = root / ".sbesm" / "index.sqlite"
    scope = [args.folder] if args.folder else None
    config = read_storage_config(root / ".sbesm" / "config.toml")

    result = run_verify(root, db_path, scope=scope, exclude_patterns=config.exclude_patterns)
    print("verify:")
    print(render_verify_summary(result.entries))
    print(f"log: {result.log_path}")

    if has_verify_findings(result.entries):
        return exitcodes.FINDINGS
    return exitcodes.SUCCESS


def _cmd_accept(args: argparse.Namespace) -> int:
    root = resolve_storage(args.storage)
    db_path = root / ".sbesm" / "index.sqlite"

    result = cmd_accept(root, db_path, args.path, apply=args.apply)
    print(f"accept {args.path!r}: old={result.old_hash} new={result.new_hash}")
    if result.applied:
        print("Applied: reference hash updated.")
    else:
        print("Preview only: pass --apply to replace the reference hash.")
    return exitcodes.SUCCESS


def _cmd_duplicates(args: argparse.Namespace) -> int:
    root = resolve_storage(args.storage)
    db_path = root / ".sbesm" / "index.sqlite"
    conn = connect(db_path)
    try:
        groups = find_duplicates(conn, min_size=args.min_size, scope=args.folder)
    finally:
        conn.close()

    if not groups:
        print("No duplicates found (index-based).")
        return exitcodes.SUCCESS

    if args.verify:
        verified_groups = verify_duplicate_groups(root, groups)
        for vg in verified_groups:
            print(f"sha256={vg.sha256} size={vg.size}")
            print("  verified duplicates:")
            for p in vg.verified_paths:
                print(f"    {p}")
            if vg.stale_paths:
                print("  stale-index (not confirmed):")
                for p in vg.stale_paths:
                    print(f"    {p}")
    else:
        print("Duplicates (index-based, not re-verified):")
        for group in groups:
            print(f"sha256={group.sha256} size={group.size}")
            for p in group.paths:
                print(f"    {p}")

    return exitcodes.FINDINGS


def _cmd_diff(args: argparse.Namespace) -> int:
    source_root = resolve_storage(args.source)
    dest_root = resolve_storage(args.dest)
    source_config = read_storage_config(source_root / ".sbesm" / "config.toml")
    dest_config = read_storage_config(dest_root / ".sbesm" / "config.toml")
    local_profiles = load_local_profiles(config_home() / "profiles.toml")

    spec = SelectionSpec(all=args.all, profile=args.profile, folders=args.folders, paths=args.paths)
    source_side = resolve_side(spec, source_root, source_config, local_profiles)
    dest_side = resolve_side(spec, dest_root, dest_config, local_profiles)

    for label, side in (("SOURCE", source_side), ("DEST", dest_side)):
        for warning in side.warnings:
            print(f"[{label}] warning: {warning}")
        if side.other_contents is not None:
            print(f"[{label}] 'other' resolved to: {side.other_contents}")

    entries = run_diff(source_side, dest_side)
    print("diff:")
    print(render_diff_report(entries))

    if has_diff_findings(entries):
        return exitcodes.FINDINGS
    return exitcodes.SUCCESS


def _cmd_sync(args: argparse.Namespace) -> int:
    source_root = resolve_storage(args.source)
    dest_root = resolve_storage(args.dest)
    source_config = read_storage_config(source_root / ".sbesm" / "config.toml")
    local_profiles = load_local_profiles(config_home() / "profiles.toml")

    spec = SelectionSpec(all=args.all, profile=args.profile, folders=args.folders, paths=args.paths)
    # sync is directional: the selection is resolved against SOURCE (what to
    # copy), and the same selector list is applied to DEST's path layout --
    # unlike diff, DEST does not get its own independently-resolved 'other'.
    source_side = resolve_side(spec, source_root, source_config, local_profiles)

    for warning in source_side.warnings:
        print(f"warning: {warning}")
    if source_side.other_contents is not None:
        print(f"'other' resolved to: {source_side.other_contents}")

    result = run_sync(
        source_root,
        dest_root,
        source_side.selectors,
        delete=args.delete,
        update=args.update,
        overwrite_conflicts=args.overwrite_conflicts,
        apply=args.apply,
    )

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"sync [{mode}]:")
    for outcome in result.outcomes:
        if outcome.skipped_reason:
            print(f"  {outcome.selector}: skipped ({outcome.skipped_reason})")
        else:
            print(f"  {outcome.selector}: rsync exit={outcome.rsync_returncode}")
    if result.conflicts:
        print("  conflicts:")
        for e in result.conflicts:
            print(f"    {e.relative_path}")
    if result.dest_only:
        label = "deletion candidates" if args.delete else "destination-only (preserved)"
        print(f"  {label}:")
        for e in result.dest_only:
            print(f"    {e.relative_path}")
    print(f"log: {result.log_path}")

    if any(o.rsync_returncode not in (0, None) for o in result.outcomes):
        return exitcodes.IO_FAILURE

    # a successful --apply can only have reached this point with conflicts
    # already explicitly approved via --overwrite-conflicts (run_sync refuses
    # otherwise), so they're resolved, not a remaining finding.
    if result.conflicts and not result.applied:
        return exitcodes.FINDINGS
    return exitcodes.SUCCESS


def _cmd_reconcile(args: argparse.Namespace) -> int:
    root_a = resolve_storage(args.storage_a)
    root_b = resolve_storage(args.storage_b)
    config_a = read_storage_config(root_a / ".sbesm" / "config.toml")
    local_profiles = load_local_profiles(config_home() / "profiles.toml")

    spec = SelectionSpec(all=args.all, profile=args.profile, folders=args.folders, paths=args.paths)
    # mirrors sync's directional convention: resolve against A, reuse for B.
    side_a = resolve_side(spec, root_a, config_a, local_profiles)

    for warning in side_a.warnings:
        print(f"warning: {warning}")
    if side_a.other_contents is not None:
        print(f"'other' resolved to: {side_a.other_contents}")

    result = run_reconcile(root_a, root_b, side_a.selectors, policy=args.mtime_policy, apply=args.apply)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"reconcile [{mode}] --mtime {args.mtime_policy}:")
    print(render_reconcile_summary(result.entries))
    print(f"log: {result.log_path}")

    if has_reconcile_findings(result.entries):
        return exitcodes.FINDINGS
    return exitcodes.SUCCESS


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "register":
        return _cmd_register(args)
    if args.command == "unregister":
        return _cmd_unregister(args)
    if args.command == "uninit":
        return _cmd_uninit(args)
    if args.command == "storages":
        return _cmd_storages(args)
    if args.command == "index":
        return _cmd_index(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "accept":
        return _cmd_accept(args)
    if args.command == "duplicates":
        return _cmd_duplicates(args)
    if args.command == "diff":
        return _cmd_diff(args)
    if args.command == "sync":
        return _cmd_sync(args)
    if args.command == "reconcile":
        return _cmd_reconcile(args)
    return exitcodes.SUCCESS


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose, quiet=args.quiet)
    try:
        return _dispatch(args)
    except SbesmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
