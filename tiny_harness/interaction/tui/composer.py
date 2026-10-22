"""The composer (issue-25 R6.7, issue-38 R1.2): the message box, which completes ``/``
commands from the card and, after a surface command that takes a path, the path.

``Tab`` takes the suggestion when there is one, else moves focus as before. ``Backspace``
on an empty composer asks the app to remove the last attachment chip.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.message import Message
from textual.suggester import Suggester
from textual.widgets import Input

from tiny_harness.interaction.tui.media import complete_path


class ComposerSuggester(Suggester):
    """``/`` commands from the card; after ``/<name> `` of a path command, the path."""

    def __init__(self, commands: Sequence[str], path_commands: Sequence[str] = ()) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.commands = tuple(f"/{c}" for c in commands)
        self.path_prefixes = tuple(f"/{c} " for c in path_commands)

    async def get_suggestion(self, value: str) -> str | None:
        for prefix in self.path_prefixes:
            if value.startswith(prefix):
                partial = value[len(prefix) :]
                completed = complete_path(partial)
                return f"{prefix}{completed}" if completed and completed != partial else None
        for command in self.commands:
            if command.startswith(value):
                return command
        return None


class Composer(Input):
    """The message box."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "complete", "complete", show=False),
    ]

    class EmptyBackspace(Message):
        """``Backspace`` with nothing to delete."""

    def action_complete(self) -> None:
        if self._suggestion and self._suggestion != self.value:
            self.value = self._suggestion
            self.cursor_position = len(self.value)
            return
        self.screen.focus_next()

    def action_delete_left(self) -> None:
        if not self.value:
            self.post_message(self.EmptyBackspace())
            return
        super().action_delete_left()


__all__ = ["Composer", "ComposerSuggester"]
