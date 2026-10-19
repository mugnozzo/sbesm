from dataclasses import dataclass, field
from pathlib import Path

from sbesm.categories import resolve_other
from sbesm.config import StorageConfig
from sbesm.errors import UsageError
from sbesm.profiles import resolve_profile
from sbesm.selectors import normalize_selection


@dataclass
class SelectionSpec:
    all: bool = False
    profile: str | None = None
    folders: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


def validate_selection_spec(spec: SelectionSpec) -> None:
    chosen = [spec.all, spec.profile is not None, bool(spec.folders) or bool(spec.paths)]
    if sum(1 for c in chosen if c) != 1:
        raise UsageError(
            "exactly one of --all, --profile, or one/more --folder/--path "
            "selectors is required"
        )


@dataclass
class ResolvedSide:
    root: Path
    selectors: list[str] | None  # None means "whole root", no scope restriction
    other_contents: list[str] | None = None
    warnings: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)


def resolve_side(
    spec: SelectionSpec,
    root: Path,
    storage_config: StorageConfig,
    local_profiles: dict[str, list[str]] | None = None,
) -> ResolvedSide:
    validate_selection_spec(spec)

    if spec.all:
        return ResolvedSide(root=root, selectors=None, exclude_patterns=storage_config.exclude_patterns)

    if spec.profile is not None:
        categories = resolve_profile(spec.profile, storage_config, local_profiles)
        selectors: list[str] = []
        other_contents: list[str] | None = None
        for category in categories:
            if category == "other":
                other_contents = resolve_other(
                    root, storage_config.known_categories, storage_config.exclude_patterns
                )
                selectors.extend(other_contents)
            else:
                selectors.append(category)
        normalized = normalize_selection(selectors)
        return ResolvedSide(
            root=root,
            selectors=normalized.paths,
            other_contents=other_contents,
            warnings=normalized.warnings,
            exclude_patterns=storage_config.exclude_patterns,
        )

    combined = [*spec.folders, *spec.paths]
    normalized = normalize_selection(combined)
    return ResolvedSide(
        root=root,
        selectors=normalized.paths,
        warnings=normalized.warnings,
        exclude_patterns=storage_config.exclude_patterns,
    )
