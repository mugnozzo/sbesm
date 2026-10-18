"""Phase 7.5: release-candidate sanity checks."""

import tomllib
from pathlib import Path

import sbesm


def test_version_matches_between_pyproject_and_package():
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    assert data["project"]["version"] == sbesm.__version__
