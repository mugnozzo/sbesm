from pathlib import Path

from sbesm.xdg import config_home


def test_uses_xdg_config_home_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_home() == tmp_path / "sbesm"


def test_falls_back_to_home_config_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_home() == Path(tmp_path) / ".config" / "sbesm"
