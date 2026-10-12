"""The command-text parser (R6.1, R6.3, abuse case 9).

A message is a command when its only part is text matching ``/<name> <arguments>`` and
the name is registered. Anything else, an unregistered ``/name`` included, is an
ordinary message for the model.
"""

from __future__ import annotations

import re
from collections.abc import Container
from typing import Final

from a2a.types import Message

from tiny_harness.harness.commands.models import CommandCall

NAME_PATTERN: Final = re.compile(r"[a-z][a-z0-9-]*")
_COMMAND: Final = re.compile(r"^/([a-z][a-z0-9-]*)(?:\s+(.*))?$", re.DOTALL)


def parse_command_text(text: str, names: Container[str]) -> CommandCall | None:
    match = _COMMAND.match(text)
    if match is None or match.group(1) not in names:
        return None
    return CommandCall(name=match.group(1), arguments=match.group(2) or "")


def parse_command(message: Message, names: Container[str]) -> CommandCall | None:
    if len(message.parts) != 1 or not message.parts[0].HasField("text"):
        return None
    return parse_command_text(message.parts[0].text, names)


__all__ = ["NAME_PATTERN", "parse_command", "parse_command_text"]
