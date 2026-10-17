import pytest

from sbesm import cli


def test_top_level_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0


def test_init_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["init", "--help"])
    assert exc_info.value.code == 0
