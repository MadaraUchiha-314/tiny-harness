"""Which configuration file is in effect, and the default one (issue-25 R2, R11.1).

The CLI reads ``--config`` when given and ``~/.tiny-harness/config.toml`` otherwise,
creating that default on first use. Both steps are functions here so an SDK caller can do
exactly what the CLI does; ``Settings.load`` itself never looks at the home directory
(R11.2).

The default file is created defensively (abuse cases 7-8): the home and the file are
``lstat``-ed, a symlink, another file type or another owner is refused, the home is made
``0700`` and the file is opened ``O_EXCL | O_NOFOLLOW`` at ``0600``. Every refusal is a
``ConfigError`` naming the path, so the CLI exits 2 and nothing is written. An existing
file is never rewritten (R2.6).
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from tiny_harness.errors import ConfigError

DEFAULT_HOME: Final = Path("~/.tiny-harness")  # expanded at call time
CONFIG_NAME: Final = "config.toml"
HOME_MODE: Final = 0o700
FILE_MODE: Final = 0o600
_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class ConfigSource(BaseModel, frozen=True, extra="forbid"):
    """The configuration file in effect and where its path came from."""

    path: Path
    origin: Literal["flag", "default"]


def resolve_config_path(explicit: Path | None, *, home: Path | None = None) -> ConfigSource:
    """``explicit`` (``--config``) when given, else ``<home>/config.toml`` (R2.1-2.3).

    Touches nothing: a missing explicit file still fails in ``Settings.load``."""
    if explicit is not None:
        return ConfigSource(path=explicit, origin="flag")
    return ConfigSource(path=(home or DEFAULT_HOME).expanduser() / CONFIG_NAME, origin="default")


def _toml_string(value: Path) -> str:
    # A JSON string is a valid TOML basic string (same escapes for quotes, \ and controls).
    return json.dumps(str(value), ensure_ascii=False)


def default_config_text(home: Path) -> str:
    """The commented default configuration (R2.5). Paths are absolute under ``home``, so
    the store does not move with the working directory (R2.8)."""
    root = home.expanduser().absolute()
    store = _toml_string(root / "tiny-harness.sqlite3")
    return f"""\
# tiny-harness configuration, created on first run. Edit freely: it is never rewritten.
# Secrets never go here; they come from the environment (OPENAI_API_KEY).
# The Temporal database (temporal.sqlite3) and the TUI log (tiny-harness.log) are kept
# beside the store below.

[temporal]
mode = "embedded"            # a local Temporal dev server inside this process

[temporal.embedded]
persist = true               # tasks survive restarts; database beside the store

[openai]
model = "gpt-6.1-sol"        # OPENAI_API_KEY from the environment, or set base_url

[server]
bind = "127.0.0.1:8080"                # where `tiny-harness serve` listens
base_url = "http://127.0.0.1:8080"     # the URL clients reach the server at

[store]
sqlite_path = {store}   # tasks, plans and history
"""


def _refuse(path: Path, why: str) -> ConfigError:
    return ConfigError(f"refusing the default configuration: {why}", variable=str(path))


def _check_owned(path: Path, info: os.stat_result, geteuid: Callable[[], int]) -> None:
    if info.st_uid != geteuid():
        raise _refuse(path, "not owned by the current user")


def _ensure_home(root: Path) -> None:
    """Create ``root`` at ``0700`` if missing; refuse a symlink or a non-directory. A
    creation race is re-checked, never trusted. The owner is checked on the open handle."""
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        try:
            os.mkdir(root, HOME_MODE)
            os.chmod(root, HOME_MODE)  # the umask may have narrowed it; never widened
        except FileExistsError:
            pass
        except OSError as exc:
            raise _refuse(root, f"cannot create the directory: {exc.strerror}") from exc
        info = os.lstat(root)
    except OSError as exc:
        raise _refuse(root, f"cannot inspect the directory: {exc.strerror}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise _refuse(root, "the directory is a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise _refuse(root, "not a directory")


def _existing(path: Path, directory: int, geteuid: Callable[[], int]) -> bool:
    """Whether the file exists as a regular file owned by the user; refuse anything else."""
    try:
        info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise _refuse(path, f"cannot inspect the file: {exc.strerror}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise _refuse(path, "the file is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise _refuse(path, "not a regular file")
    _check_owned(path, info, geteuid)
    return True


def _create(path: Path, directory: int, text: str) -> bool:
    """Write ``text`` to a new file; ``False`` when another process created it first."""
    try:
        fd = os.open(path.name, _CREATE_FLAGS, FILE_MODE, dir_fd=directory)
    except FileExistsError:
        return False
    except OSError as exc:
        raise _refuse(path, f"cannot create the file: {exc.strerror}") from exc
    try:
        os.fchmod(fd, FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
    except OSError as exc:
        raise _refuse(path, f"cannot write the file: {exc.strerror}") from exc
    finally:
        if fd != -1:
            os.close(fd)
    return True


def ensure_default_config(
    home: Path | None = None, *, geteuid: Callable[[], int] = os.geteuid
) -> tuple[Path, bool]:
    """Create ``<home>/config.toml`` if missing; return ``(path, created)``.

    ``home`` defaults to ``~/.tiny-harness``. An existing regular file owned by the user is
    returned untouched. Raises ``ConfigError`` naming the path for anything unsafe or any
    OS failure, and never falls back to an empty configuration."""
    root = (home or DEFAULT_HOME).expanduser().absolute()
    path = root / CONFIG_NAME
    _ensure_home(root)
    try:
        # Held open so the checks and the create see the same directory, not a swapped one.
        directory = os.open(root, _DIR_FLAGS)
    except OSError as exc:
        raise _refuse(root, f"cannot open the directory: {exc.strerror}") from exc
    try:
        _check_owned(root, os.fstat(directory), geteuid)
        if _existing(path, directory, geteuid):
            return path, False
        if _create(path, directory, default_config_text(root)):
            return path, True
        _existing(path, directory, geteuid)  # lost a creation race: re-check the winner
        return path, False
    finally:
        os.close(directory)


__all__ = [
    "CONFIG_NAME",
    "DEFAULT_HOME",
    "ConfigSource",
    "default_config_text",
    "ensure_default_config",
    "resolve_config_path",
]
