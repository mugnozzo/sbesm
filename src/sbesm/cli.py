import argparse
import sys
from pathlib import Path

from sbesm import exitcodes
from sbesm.config import read_storage_config
from sbesm.db import connect
from sbesm.errors import SbesmError
from sbesm.indexing import has_findings, render_preview, run_index
from sbesm.init_cmd import cmd_init
from sbesm.logging_setup import configure_logging
from sbesm.register_cmd import cmd_register
from sbesm.registry import classify_registry, load_registry
from sbesm.resolve import resolve_storage
from sbesm.status import compute_category_presence, compute_counts, last_run_summary
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

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    config = cmd_init(Path(args.root), name=args.name)
    print(f"Initialized storage '{config.name}' (id={config.id}) at {args.root}")
    return exitcodes.SUCCESS


def _cmd_register(args: argparse.Namespace) -> int:
    entry = cmd_register(Path(args.root), name=args.name)
    print(f"Registered '{entry.name}' -> {entry.last_known_root} (id={entry.storage_id})")
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

    result = run_index(
        root, db_path, scope=scope, plan_only=args.plan_only, rehash=args.rehash, apply=args.apply
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


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "register":
        return _cmd_register(args)
    if args.command == "storages":
        return _cmd_storages(args)
    if args.command == "index":
        return _cmd_index(args)
    if args.command == "status":
        return _cmd_status(args)
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
