import argparse
import sys

from sbesm import exitcodes
from sbesm.errors import SbesmError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sbesm",
        description="Simple But Easy Synchronization Manager",
    )
    return parser


def _dispatch(args: argparse.Namespace) -> int:
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
