import logging
import sys
from typing import IO


def configure_logging(
    verbose: bool = False, quiet: bool = False, stream: IO[str] | None = None
) -> logging.Logger:
    if verbose and quiet:
        raise ValueError("verbose and quiet are mutually exclusive")

    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO

    logger = logging.getLogger("sbesm")
    logger.handlers.clear()
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
