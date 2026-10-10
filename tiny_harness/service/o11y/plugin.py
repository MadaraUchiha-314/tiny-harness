"""The o11y plugin (R17.3): a programmatic Agent Plugin whose one hook is the executor."""

from __future__ import annotations

from tiny_harness.harness.plugins import HookDef, Plugin, PluginManifest
from tiny_harness.service.o11y.hook import O11yExecutor

PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

executor = O11yExecutor()
"""The process-wide executor the plugin's hook definition imports."""


def o11y_plugin() -> Plugin:
    return Plugin(
        manifest=PluginManifest.model_validate(
            {
                "$schema": PLUGIN_SCHEMA,
                "name": "o11y",
                "description": "Spans and structured logs on every lifecycle operation (R17)",
            }
        ),
        hooks=(
            HookDef(
                name="o11y", priority=0, import_path="tiny_harness.service.o11y.plugin:executor"
            ),
        ),
    )


__all__ = ["PLUGIN_SCHEMA", "executor", "o11y_plugin"]
