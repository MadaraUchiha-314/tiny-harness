"""Abuse cases 7-8 (issue-25): the default home and file are never followed through a
symlink, never taken from another user, and are created ``0700`` / ``0600``. Every refusal
is a ``ConfigError`` naming the path, and nothing is written."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tiny_harness.errors import ConfigError
from tiny_harness.home import CONFIG_NAME, ensure_default_config


def refused(home: Path, *, uid: int | None = None) -> ConfigError:
    euid = os.geteuid() if uid is None else uid
    with pytest.raises(ConfigError) as caught:
        ensure_default_config(home, geteuid=lambda: euid)
    return caught.value


# Abuse case 7 — symlinks and foreign owners.


def test_a_symlinked_home_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    home = tmp_path / "home"
    home.symlink_to(target, target_is_directory=True)
    assert refused(home).variable == str(home)
    assert list(target.iterdir()) == []


def test_a_symlinked_file_is_refused_and_its_target_untouched(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    target = tmp_path / "victim.txt"
    target.write_text("keep me")
    (home / CONFIG_NAME).symlink_to(target)
    assert refused(home).variable == str(home / CONFIG_NAME)
    assert target.read_text() == "keep me"


def test_a_dangling_symlinked_file_is_refused_and_not_created(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    target = tmp_path / "planted.toml"
    (home / CONFIG_NAME).symlink_to(target)
    assert refused(home).variable == str(home / CONFIG_NAME)
    assert not target.exists()


def test_a_home_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.write_text("a file")
    assert refused(home).variable == str(home)
    assert home.read_text() == "a file"


def test_a_config_that_is_not_a_regular_file_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / CONFIG_NAME).mkdir(parents=True)
    assert refused(home).variable == str(home / CONFIG_NAME)


def test_a_home_owned_by_another_user_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    assert refused(home, uid=os.geteuid() + 1).variable == str(home)
    assert list(home.iterdir()) == []


def test_a_config_owned_by_another_user_is_refused(tmp_path: Path) -> None:
    """Simulated: the home is checked against the real uid, the file against another one."""
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    path = home / CONFIG_NAME
    path.write_text("# theirs\n")
    real = os.geteuid()
    calls = iter([real, real + 1])
    with pytest.raises(ConfigError) as caught:
        ensure_default_config(home, geteuid=lambda: next(calls, real + 1))
    assert caught.value.variable == str(path)
    assert path.read_text() == "# theirs\n"


# Abuse case 8 — modes.


def test_created_modes_are_owner_only_whatever_the_umask(tmp_path: Path) -> None:
    previous = os.umask(0)
    try:
        path, created = ensure_default_config(tmp_path / "home")
    finally:
        os.umask(previous)
    assert created
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
