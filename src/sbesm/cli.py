import argparse
import sys
from pathlib import Path

from sbesm import exitcodes
from sbesm.errors import SbesmError
from sbesm.init_cmd import cmd_init
from sbesm.logging_setup import configure_logging
from sbesm.register_cmd import cmd_register
from sbesm.registry import classify_registry, load_registry
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


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "register":
        return _cmd_register(args)
    if args.command == "storages":
        return _cmd_storages(args)
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
