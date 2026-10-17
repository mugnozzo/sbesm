import argparse
import sys

from sbesm import exitcodes
from sbesm.errors import SbesmError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sbesm",
        description="Simple But Easy Synchronization Manager",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Initialize a new managed storage root"
    )
    init_parser.add_argument("root")
    init_parser.add_argument("--name")

    return parser


def _cmd_init_stub(args: argparse.Namespace) -> int:
    print(f"init: not implemented yet (root={args.root!r}, name={args.name!r})")
    return exitcodes.NOT_IMPLEMENTED


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return _cmd_init_stub(args)
    return exitcodes.SUCCESS


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except SbesmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
