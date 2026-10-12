"""``tiny_harness.home`` (issue-25 R2, R11.1): which configuration file is in effect, and
the default file at ``~/.tiny-harness/config.toml`` created once and never rewritten."""

from __future__ import annotations

import stat
import tomllib
from pathlib import Path

import pytest

from tiny_harness.config import Settings
from tiny_harness.errors import ConfigError
from tiny_harness.home import (
    CONFIG_NAME,
    DEFAULT_HOME,
    ConfigSource,
    default_config_text,
    ensure_default_config,
    resolve_config_path,
)

ENV = {"OPENAI_API_KEY": "sk-test"}


# R2.1-2.3 — resolution.


def test_the_flag_wins_and_names_its_origin(tmp_path: Path) -> None:
    explicit = tmp_path / "demo.toml"
    assert resolve_config_path(explicit, home=tmp_path / "home") == ConfigSource(
        path=explicit, origin="flag"
    )
    assert not (tmp_path / "home").exists()


def test_without_the_flag_the_default_file_under_home(tmp_path: Path) -> None:
    source = resolve_config_path(None, home=tmp_path / "home")
    assert source == ConfigSource(path=tmp_path / "home" / CONFIG_NAME, origin="default")
    assert not (tmp_path / "home").exists()


def test_the_default_home_is_expanded_from_the_user_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert Path("~/.tiny-harness") == DEFAULT_HOME
    assert resolve_config_path(None).path == tmp_path / ".tiny-harness" / "config.toml"


def test_resolution_never_creates_anything(tmp_path: Path) -> None:
    resolve_config_path(None, home=tmp_path / "home")
    resolve_config_path(tmp_path / "missing.toml", home=tmp_path / "home")
    assert list(tmp_path.iterdir()) == []


# R2.5 — the default text.


def test_the_default_text_is_valid_configuration_with_absolute_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / CONFIG_NAME
    path.write_text(default_config_text(home))
    settings = Settings.load(path, env=ENV)
    assert settings.temporal.mode == "embedded"
    assert settings.temporal.embedded is not None and settings.temporal.embedded.persist
    assert settings.store.sqlite_path == home / "tiny-harness.sqlite3"
    assert settings.store.sqlite_path.is_absolute()
    assert settings.temporal.database_path(settings.store) == home / "temporal.sqlite3"
    assert settings.server.ui_dir is None


def test_the_default_text_documents_every_key_and_holds_no_secret(tmp_path: Path) -> None:
    text = default_config_text(tmp_path)
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            assert "#" in line, f"undocumented key: {line}"
    assert "api_key" not in tomllib.loads(text).get("openai", {})
    assert "key" not in str(tomllib.loads(text)).lower()
    assert "OPENAI_API_KEY" in text  # the header says where the secret comes from


def test_the_default_text_quotes_unusual_home_paths(tmp_path: Path) -> None:
    home = tmp_path / 'a "quoted" \\ home'
    data = tomllib.loads(default_config_text(home))
    assert data["store"]["sqlite_path"] == str(home / "tiny-harness.sqlite3")


# R2.4, R2.6 — creation.


def test_a_missing_default_is_created(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path, created = ensure_default_config(home)
    assert (path, created) == (home / CONFIG_NAME, True)
    assert path.read_text() == default_config_text(home)
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_existing_default_is_used_untouched(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    path = home / CONFIG_NAME
    path.write_text("# mine\n")
    before = path.stat()
    assert ensure_default_config(home) == (path, False)
    assert path.read_text() == "# mine\n"
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_an_existing_invalid_default_is_not_replaced(tmp_path: Path) -> None:
    """R2.7: the file is kept; loading it fails with today's error naming the file."""
    home = tmp_path / "home"
    home.mkdir()
    path = home / CONFIG_NAME
    path.write_text("not = [valid")
    assert ensure_default_config(home) == (path, False)
    with pytest.raises(ConfigError) as caught:
        Settings.load(path, env=ENV)
    assert caught.value.variable == str(path)
    assert path.read_text() == "not = [valid"


def test_a_missing_parent_is_a_config_error_naming_the_path(tmp_path: Path) -> None:
    home = tmp_path / "absent" / "home"
    with pytest.raises(ConfigError) as caught:
        ensure_default_config(home)
    assert caught.value.variable == str(home)
