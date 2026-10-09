"""The built-in plugin: the opinionated defaults, loaded first and overridable (R3.9).

It is an Agent Plugins directory like any other (``plugin.json`` beside this file, the
namespace directory with ``systemprompt.md``), loaded by the same loader before the
operator's plugins. The intrinsic tools and the default ``in`` bodies register through
``register_defaults`` as later layers add them.
"""

from __future__ import annotations

from pathlib import Path

from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.plugins import LoadReport, PluginLoader, Registrar

BUILTIN_ROOT = Path(__file__).resolve().parent


async def load_builtin(
    *, hook_manager: HookManager, registrar: Registrar, data_root: Path
) -> LoadReport:
    """Load the built-in plugin first; its registrations are the defaults every operator
    plugin may override (R3.9)."""
    loader = PluginLoader(hook_manager=hook_manager, registrar=registrar, data_root=data_root)
    return await loader.load_directory(BUILTIN_ROOT)


__all__ = ["BUILTIN_ROOT", "load_builtin"]
