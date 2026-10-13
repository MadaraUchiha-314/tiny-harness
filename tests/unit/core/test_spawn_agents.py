"""``spawn_subtask`` names only a registered agent (issue-34 R3)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from a2a.types import AgentCard, Message, Task

from tiny_harness.harness.agents import A2AEvent, Agent
from tiny_harness.harness.core import HarnessTask, TaskExtensionData
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.core.intrinsics import TaskContext, core_intrinsics
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.models import FakeLLM
from tiny_harness.harness.persistence import SqliteStore
from tiny_harness.harness.tools import Tool, ToolCall, ToolResult, WorkflowCommand


class IdleAgent(Agent):
    """A registered agent that is never called by these tests."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(EntityRef(kind=EntityKind.AGENT, id=agent_id), AgentCard(name=agent_id))

    async def send_message(
        self, request: Message, *, extensions: Sequence[str] = ()
    ) -> AsyncIterator[A2AEvent]:
        raise AssertionError("the agent must not be contacted")
        yield  # pragma: no cover

    async def cancel_task(self, task_id: str) -> Task:
        raise AssertionError("the agent must not be contacted")


def task() -> HarnessTask:
    return HarnessTask.new("t-1", "ctx-1", TaskExtensionData(name="n", goal="g"))


def spawn(agent: str | None) -> ToolCall:
    return ToolCall(
        call_id="c1",
        name="spawn_subtask",
        arguments={"name": "Check", "goal": "Check the ledger", "agent": agent},
    )


async def invoke(agent: str | None, known: Sequence[str]) -> ToolResult | WorkflowCommand:
    tools = {
        t.ref.id: t
        for t in core_intrinsics(TaskContext(task()), known_agents=lambda: frozenset(known))
    }
    return await tools["spawn_subtask"].invoke(spawn(agent))


async def test_an_unknown_agent_is_an_error_listing_the_valid_ids() -> None:
    out = await invoke("billing", ["ledger", "audit"])
    assert isinstance(out, ToolResult) and out.is_error
    text = out.content[0].text or ""
    assert "agent.unknown" in text
    assert "'billing'" in text
    assert "audit, ledger" in text


async def test_with_no_agents_registered_the_error_says_so() -> None:
    out = await invoke("ledger", [])
    assert isinstance(out, ToolResult) and out.is_error
    assert "none are registered" in (out.content[0].text or "")


async def test_an_empty_agent_id_is_an_error_not_a_local_run() -> None:
    out = await invoke("", ["ledger"])
    assert isinstance(out, ToolResult) and out.is_error


async def test_a_registered_agent_delegates_as_before() -> None:
    out = await invoke("ledger", ["ledger"])
    assert isinstance(out, WorkflowCommand)
    assert out.kind == "spawn_subtask" and out.payload["agent"] == "ledger"


async def test_a_null_agent_runs_locally_as_before() -> None:
    out = await invoke(None, [])
    assert isinstance(out, WorkflowCommand)
    assert out.kind == "spawn_subtask" and out.payload["agent"] is None


async def test_the_host_checks_against_the_registry_at_call_time() -> None:
    registry = Registry()
    ops = InProcessOperations(
        registry=registry,
        hooks=HookManager(),
        llm=FakeLLM([]),
        store=SqliteStore(":memory:"),
        system_prompt="SYS",
    )
    await ops.bind()
    tool = await ops.registry.get(EntityRef(kind=EntityKind.TOOL, id="spawn_subtask"), Tool)
    ops.context.task = task()
    assert isinstance(await tool.invoke(spawn("ledger")), ToolResult)
    agent = IdleAgent("ledger")
    await registry.add(RegistryEntry(ref=agent.ref, instance=agent))
    assert isinstance(await tool.invoke(spawn("ledger")), WorkflowCommand)


async def test_an_empty_agent_id_is_refused_even_when_one_is_registered() -> None:
    """Critic C1: an operator-configured ``id = ""`` must not turn into a local run."""
    out = await invoke("", ["", "ledger"])
    assert isinstance(out, ToolResult) and out.is_error
    assert "[agent.unknown]" in (out.content[0].text or "")


async def test_a_local_sub_task_carries_its_description_to_the_child() -> None:
    """issue-34 R7.2: ``spawn_subtask`` takes the context an isolated sub-task needs."""
    tools = {t.ref.id: t for t in core_intrinsics(TaskContext(task()))}
    call = ToolCall(
        call_id="c1",
        name="spawn_subtask",
        arguments={
            "name": "Summarise",
            "goal": "Summarise the refund policy",
            "description": "The policy is in the policy tool; the customer is in the EU.",
            "acceptance_criteria": ["Names the refund window"],
        },
    )
    out = await tools["spawn_subtask"].invoke(call)
    assert isinstance(out, WorkflowCommand)
    assert out.payload["description"] == (
        "The policy is in the policy tool; the customer is in the EU."
    )
    assert out.payload["agent"] is None
