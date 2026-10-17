from sbesm import cli, exitcodes


def test_init_success_path(tmp_path, capsys):
    root = tmp_path / "storage1"
    code = cli.main(["init", str(root), "--name", "backup1"])

    assert code == exitcodes.SUCCESS
    assert (root / ".sbesm" / "config.toml").exists()
    out = capsys.readouterr().out
    assert "backup1" in out


def test_init_rejects_file_not_dir(tmp_path, capsys):
    root = tmp_path / "not_a_dir"
    root.write_text("i am a file")

    code = cli.main(["init", str(root)])

    assert code == exitcodes.USAGE_ERROR
    err = capsys.readouterr().err
    assert "not a directory" in err


def test_init_rejects_repeat_initialization(tmp_path, capsys):
    root = tmp_path / "storage1"
    assert cli.main(["init", str(root), "--name", "backup1"]) == exitcodes.SUCCESS

    code = cli.main(["init", str(root), "--name", "backup1"])

    assert code == exitcodes.USAGE_ERROR
    err = capsys.readouterr().err
    assert "already" in err


def test_init_rejects_nested_under_existing_storage(tmp_path, capsys):
    parent = tmp_path / "storage1"
    assert cli.main(["init", str(parent), "--name", "backup1"]) == exitcodes.SUCCESS

    nested = parent / "subdir"
    nested.mkdir()
    code = cli.main(["init", str(nested)])

    assert code == exitcodes.USAGE_ERROR
    err = capsys.readouterr().err
    assert "nested" in err
