from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sbesm.errors import UsageError


@dataclass
class NormalizedSelection:
    paths: list[str]
    warnings: list[str] = field(default_factory=list)


def normalize_selector(selector: str) -> str:
    if not selector:
        raise UsageError("selector must not be empty")

    pure = PurePosixPath(selector)
    if pure.is_absolute():
        raise UsageError(f"selector must be a relative path, got {selector!r}")
    if ".." in pure.parts:
        raise UsageError(f"selector must not contain '..': {selector!r}")

    parts = [part for part in pure.parts if part != "."]
    if not parts:
        raise UsageError(f"selector must not be empty: {selector!r}")
    if parts[0] == ".sbesm":
        raise UsageError(
            f"selector must not reference the reserved .sbesm directory: {selector!r}"
        )

    return "/".join(parts)


def normalize_selection(selectors: list[str]) -> NormalizedSelection:
    normalized = sorted(
        {normalize_selector(selector) for selector in selectors},
        key=lambda s: (s.count("/"), s),
    )

    kept: list[str] = []
    warnings: list[str] = []
    for selector in normalized:
        broader = next(
            (
                existing
                for existing in kept
                if selector == existing or selector.startswith(existing + "/")
            ),
            None,
        )
        if broader is not None:
            warnings.append(
                f"selector {selector!r} is nested under {broader!r}; "
                f"collapsing into the broader selector"
            )
            continue
        kept.append(selector)

    return NormalizedSelection(paths=kept, warnings=warnings)
