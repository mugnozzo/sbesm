from sbesm import exitcodes


def test_exit_codes_are_distinct():
    values = [
        exitcodes.SUCCESS,
        exitcodes.FINDINGS,
        exitcodes.USAGE_ERROR,
        exitcodes.STORAGE_NOT_FOUND,
        exitcodes.IO_FAILURE,
        exitcodes.INTERRUPTED,
    ]
    assert len(values) == len(set(values))


if __name__ == "__main__":
    test_exit_codes_are_distinct()
    print("ok")
