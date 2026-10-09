"""Feature: Plugins
Requirement: docs/specs/issue-3/requirements.md#R3

The built-in plugin loads first and is overridable.
"""

from pathlib import Path

from tiny_harness.builtin import load_builtin
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.plugins import ComponentKind, PluginLoader
from tiny_harness.harness.plugins.registrar import RegistryRegistrar
from tiny_harness.harness.prompts import SYSTEM_PROMPT_ID, PromptEntity

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugins"


async def test_the_builtin_plugin_loads_first_and_is_overridable_by_a_later_plugin(
    tmp_path: Path,
) -> None:
    """
    Feature: Plugins
    Requirement: docs/specs/issue-3/requirements.md#R3

    Scenario: the built-in plugin loads first and is overridable by a lower-priority executor
        Given an empty registry and hook manager
        When the built-in plugin is loaded, then the fixture plugin with override
        Then the default system prompt is registered first
        And the fixture plugin's systemprompt.md replaces it
        And the fixture plugin's skill and prompt are registered as entities
    """
    registry = Registry()
    hooks = HookManager()
    registrar = RegistryRegistrar(registry)
    report = await load_builtin(hook_manager=hooks, registrar=registrar, data_root=tmp_path)
    assert report.plugin == "tiny-harness-builtin"
    assert report.loaded_ids(ComponentKind.SYSTEM_PROMPT) == (SYSTEM_PROMPT_ID,)
    assert report.skipped == ()
    system_ref = EntityRef(kind=EntityKind.PROMPT, id=SYSTEM_PROMPT_ID)
    default = await registry.get(system_ref, PromptEntity)
    assert default.section("role") is not None and "tiny-harness" in (default.section("role") or "")

    registrar.override = True
    loader = PluginLoader(hook_manager=hooks, registrar=registrar, data_root=tmp_path)
    second = await loader.load_directory(FIXTURES / "valid", override=True)
    assert second.loaded_ids(ComponentKind.SYSTEM_PROMPT) == (SYSTEM_PROMPT_ID,)
    replaced = await registry.get(system_ref, PromptEntity)
    assert replaced.section("role") == "You are the support agent."
    assert registry.list(EntityKind.SKILL) == [
        EntityRef(kind=EntityKind.SKILL, id="summarize", version="1.2.0")
    ]
    assert EntityRef(kind=EntityKind.PROMPT, id="participants", version="1.2.0") in registry.list(
        EntityKind.PROMPT
    )
    assert set(registrar.catalog.servers) == {"support-tools/orders", "support-tools/policy"}
