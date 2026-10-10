"""The TUI renderer (R20.2, R20.3, R20.6): a Textual app that is an A2A client and nothing else."""

from tiny_harness.interaction.tui.app import HarnessApp, run_tui
from tiny_harness.interaction.tui.client import (
    A2AClientPort,
    EventSource,
    ScriptedClient,
    SdkClient,
)

__all__ = ["A2AClientPort", "EventSource", "HarnessApp", "ScriptedClient", "SdkClient", "run_tui"]
