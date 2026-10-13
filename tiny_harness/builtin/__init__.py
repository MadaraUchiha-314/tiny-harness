"""The built-in plugin: the opinionated defaults, loaded first and overridable (R3.9).

It is an Agent Plugins directory like any other (``plugin.json`` beside this file, the
namespace directory with ``systemprompt.md``), loaded by the same loader before the
operator's plugins. The intrinsic tools and the default ``in`` bodies register through
``register_defaults`` as later layers add them. With a command registry it also
registers the command role policy and, given the model catalog, the built-in commands
``/model``, ``/effort``, ``/sub-task``, ``/status`` and ``/exit`` (issue-25 R6.8, R6a.3;
issue-32).
"""

from __future__ import annotations

from pathlib import Path

from tiny_harness.harness.commands import (
    CommandRegistry,
    register_builtin_commands,
    register_role_policy,
)
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.models import ModelCatalog
from tiny_harness.harness.plugins import LoadReport, PluginLoader, Registrar

BUILTIN_ROOT = Path(__file__).resolve().parent


async def load_builtin(
    *,
    hook_manager: HookManager,
    registrar: Registrar,
    data_root: Path,
    commands: CommandRegistry | None = None,
    catalog: ModelCatalog | None = None,
) -> LoadReport:
    """Load the built-in plugin first; its registrations are the defaults every operator
    plugin may override (R3.9). ``catalog`` (with ``commands``) adds the built-in
    commands; without it the harness has none (R6.8)."""
    if commands is not None:
        register_role_policy(hook_manager)
        if catalog is not None:
            register_builtin_commands(commands, catalog)
    loader = PluginLoader(
        hook_manager=hook_manager, registrar=registrar, data_root=data_root, commands=commands
    )
    return await loader.load_directory(BUILTIN_ROOT)


__all__ = ["BUILTIN_ROOT", "load_builtin"]
