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


# Critic round 1 (C2, C3) — races during the first run.


def test_a_home_swapped_for_a_symlink_after_mkdir_changes_no_other_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Feature: Safe first run (abuse cases 7, 8)
    Scenario: the new home is replaced by a symlink between mkdir and chmod
        Given another directory at mode 0755
        And a race that renames the just-created home and links it to that directory
        When the default configuration is ensured
        Then it is refused as a symlink
        And the other directory's mode is still 0755
    """
    other = tmp_path / "other"
    other.mkdir()
    other.chmod(0o755)
    home = tmp_path / "home"
    real_mkdir = os.mkdir

    def racing_mkdir(path: str | os.PathLike[str], mode: int = 0o777) -> None:
        real_mkdir(path, mode)
        os.rename(path, tmp_path / "moved")
        os.symlink(other, path)

    monkeypatch.setattr(os, "mkdir", racing_mkdir)
    error = refused(home)
    assert "symlink" in str(error)
    assert stat.S_IMODE(other.stat().st_mode) == 0o755


def test_the_file_appears_only_once_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Feature: Safe first run
    Scenario: a concurrent first run never sees a partial configuration
        Given no default configuration yet
        When the file's content is being written
        Then config.toml does not exist under its final name yet
        And afterwards it exists with the whole content, at 0600, with no temporary left
    """
    home = tmp_path / "home"
    seen: list[bool] = []
    real_fdopen = os.fdopen

    def spying_fdopen(fd: int, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        seen.append((home / CONFIG_NAME).exists())
        return real_fdopen(fd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "fdopen", spying_fdopen)
    path, created = ensure_default_config(home)
    assert created and seen == [False]
    assert "[temporal]" in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sorted(p.name for p in home.iterdir()) == [CONFIG_NAME]
