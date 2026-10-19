from sbesm.exclude import is_name_excluded


def test_literal_match():
    assert is_name_excluded("__pycache__", ["__pycache__"])


def test_glob_match():
    assert is_name_excluded("module.pyc", ["*.pyc"])


def test_no_match():
    assert not is_name_excluded("documents", ["__pycache__", "*.pyc"])


def test_empty_patterns_never_excludes():
    assert not is_name_excluded("__pycache__", [])
