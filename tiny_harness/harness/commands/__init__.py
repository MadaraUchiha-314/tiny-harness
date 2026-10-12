"""Slash commands: models, the ``command.invoked`` contexts, the parser, the registry and
the built-in commands (R6, R6a, R7-R10)."""

from tiny_harness.harness.commands.builtins import (
    BUILTIN_SPECS,
    EFFORTS,
    ROLE_POLICY_PRIORITY,
    effort_command,
    model_command,
    register_builtin_commands,
    register_role_policy,
    status_command,
    sub_task_command,
)
from tiny_harness.harness.commands.models import (
    ChildSnapshot,
    CommandCall,
    CommandInvokedIn,
    CommandInvokedPost,
    CommandInvokedPre,
    CommandResult,
    CommandSpec,
    SpawnIntent,
    TaskSettings,
    TaskSnapshot,
)
from tiny_harness.harness.commands.parse import NAME_PATTERN, parse_command, parse_command_text
from tiny_harness.harness.commands.registry import (
    COMMAND_IN,
    Command,
    CommandHandler,
    CommandRegistry,
)

__all__ = [
    "BUILTIN_SPECS",
    "COMMAND_IN",
    "EFFORTS",
    "NAME_PATTERN",
    "ROLE_POLICY_PRIORITY",
    "ChildSnapshot",
    "Command",
    "CommandCall",
    "CommandHandler",
    "CommandInvokedIn",
    "CommandInvokedPost",
    "CommandInvokedPre",
    "CommandRegistry",
    "CommandResult",
    "CommandSpec",
    "SpawnIntent",
    "TaskSettings",
    "TaskSnapshot",
    "effort_command",
    "model_command",
    "parse_command",
    "parse_command_text",
    "register_builtin_commands",
    "register_role_policy",
    "status_command",
    "sub_task_command",
]
