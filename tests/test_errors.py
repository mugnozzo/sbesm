from unittest import mock

from sbesm import cli, exitcodes
from sbesm.errors import UsageError


def test_usage_error_maps_to_usage_error_exit_code():
    with mock.patch.object(cli, "_dispatch", side_effect=UsageError("bad args")):
        code = cli.main([])
    assert code == exitcodes.USAGE_ERROR


if __name__ == "__main__":
    test_usage_error_maps_to_usage_error_exit_code()
    print("ok")
