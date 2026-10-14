"""Feature: five agents in one app
Requirement: docs/specs/issue-36/requirements.md#R5, #R6

The issue's acceptance test: ``examples/multi_agent``'s five configurations, mounted in one
app on one real loopback port, with one shared embedded Temporal dev server from the
process's pool. Agents delegate to each other over HTTP through their own routes, and a
parked remote task's push reaches the delegating agent's prefixed push route.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from a2a.types import Task, TaskState
from starlette.types import ASGIApp

from examples.multi_agent import app as starlette_example
from examples.multi_agent import app_fastapi as fastapi_example
from tests.integration.mount.conftest import ENV, ask, free_port, serving
from tiny_harness.config import Settings
from tiny_harness.harness.core import HarnessTask
from tiny_harness.harness.models import FakeLLM, LLMResponse, scripted
from tiny_harness.harness.persistence import Filter, PushConfigRecord, TaskRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service import Harness
from tiny_harness.service.durable.pool import PROCESS_POOL

EXAMPLE = Path(starlette_example.__file__).parent

Builder = Callable[..., tuple[ASGIApp, list[Harness]]]


def delegate(agent: str, goal: str) -> ToolCall:
    return ToolCall(
        call_id=f"spawn-{agent}",
        name="spawn_subtask",
        arguments={"name": f"Ask {agent}", "goal": goal, "agent": agent},
    )


def ask_back(participant: str, question: str) -> ToolCall:
    return ToolCall(
        call_id="ask-1",
        name="ask_participant",
        arguments={"participant_id": participant, "question": question},
    )


def example_settings(tmp_path: Path, port: int) -> list[Settings]:
    """The five example configurations on ``port``, with their state in ``tmp_path``."""
    loaded: list[Settings] = []
    for name in starlette_example.AGENTS:
        text = (EXAMPLE / f"{name}.toml").read_text()
        text = text.replace("127.0.0.1:8090", f"127.0.0.1:{port}")
        text = text.replace("examples/multi_agent/.state", str(tmp_path))
        path = tmp_path / f"{name}.toml"
        path.write_text(text)
        loaded.append(Settings.load(path, env=ENV))
    return loaded


@dataclass
class Service:
    origin: str
    harnesses: dict[str, Harness]
    llms: dict[str, FakeLLM]

    async def task(self, agent: str, task_id: str) -> HarnessTask:
        handle = self.harnesses[agent].client.get_workflow_handle(task_id)
        return HarnessTask(await handle.query("task", result_type=Task))

    async def until(
        self, agent: str, task_id: str, check: Callable[[HarnessTask], bool]
    ) -> HarnessTask:
        for _ in range(600):
            current = await self.task(agent, task_id)
            if check(current):
                return current
            await asyncio.sleep(0.05)
        raise AssertionError(f"{agent}'s task {task_id} never reached the expected state")

    async def records(self, agent: str) -> list[TaskRecord]:
        store = self.harnesses[agent]._activities.engine.store  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
        return list(await store.query(TaskRecord, Filter()))

    def messages(self, agent: str) -> list[str]:
        """Every message text the agent's model was given, for a failure's message."""
        return [
            item.text
            for request in self.llms[agent].requests
            for item in request.input
            if item.kind == "message"
        ]

    def told(self, agent: str, text: str) -> bool:
        return any(
            text in item.text
            for request in self.llms[agent].requests
            for item in request.input
            if item.kind == "message"
        )


@asynccontextmanager
async def five_agents(
    tmp_path: Path, scripts: Mapping[str, Sequence[LLMResponse]], build: Builder
) -> AsyncGenerator[Service]:
    port = free_port()
    llms = {name: FakeLLM(list(scripts.get(name, ()))) for name in starlette_example.AGENTS}

    def harness(settings: Settings) -> Harness:
        return Harness(settings, llm=llms[settings.agent.id])

    app, harnesses = build(example_settings(tmp_path, port), harness=harness)
    async with serving(app, port) as origin:
        assert PROCESS_POOL.open_connections() == 1  # NFR: one Temporal connection for five
        yield Service(origin, {h.agent_id: h for h in harnesses}, llms)


def sub_task_state(state: str) -> Callable[[HarnessTask], bool]:
    return lambda t: bool(t.ext.sub_tasks) and t.ext.sub_tasks[0].state == state


@pytest.mark.parametrize(
    "build",
    [starlette_example.build_app, fastapi_example.build_app],
    ids=["starlette", "fastapi"],
)
async def test_five_agents_in_one_app_delegate_to_each_other(
    tmp_path: Path, build: Builder
) -> None:
    """
    Scenario: five agents in one app delegate to each other
        Given the five example agents mounted in one app on one port
        And agent a lists b, and agent b lists d, under [[agents]]
        When alice asks agent a a question that a delegates to b, and b to d
        Then b answers a, and a's model is told b's answer
        And d answers b, and b's model is told d's answer
        And every agent's card is served at its own prefix
        And each agent ran only its own tasks
    """
    scripts = {
        "a": [
            scripted("", tool_calls=[delegate("b", "What is the balance?")]),
            scripted("Asking billing."),
            scripted("Your balance is 42."),
        ],
        "b": [
            scripted("", tool_calls=[delegate("d", "Look up the balance.")]),
            scripted("Asking the ledger."),
            scripted("The ledger says 42."),
        ],
        "d": [scripted("Ledger: 42.")],
    }
    async with five_agents(tmp_path, scripts, build) as service:
        import httpx

        async with httpx.AsyncClient() as http:
            for name in starlette_example.AGENTS:
                card = await http.get(f"{service.origin}/agents/{name}/.well-known/agent-card.json")
                assert card.status_code == 200
                urls = {i["url"] for i in card.json()["supportedInterfaces"]}
                assert urls == {f"{service.origin}/agents/{name}/"}
        first = await ask(f"{service.origin}/agents/a", "What is my balance?")
        parent = await service.until("a", first.id, sub_task_state("COMPLETED"))
        child = parent.ext.sub_tasks[0]
        assert child.agent is not None and child.agent.id == "b"
        # b's sub-task completes when b parks (issue-25 R3.4). a's stand-in reads b's state
        # when b's push arrives (issue-34), so a is told whichever reply b has parked with
        # by then: its first, or, when d answered first, its second (learning-014). b itself
        # hears d's answer through its own stand-in.
        b_replies = ("Asking the ledger.", "The ledger says 42.")

        def a_heard_b() -> bool:
            return any(service.told("a", reply) for reply in b_replies)

        for _ in range(600):
            if a_heard_b() and service.told("b", "Ledger: 42."):
                break
            await asyncio.sleep(0.05)
        assert a_heard_b(), service.messages("a")
        assert service.told("b", "Ledger: 42."), service.messages("b")
        assert {r.task_id for r in await service.records("c")} == set()
        assert {r.task_id for r in await service.records("e")} == set()
        d_tasks = await service.records("d")
        assert d_tasks and all(
            HarnessTask(r.task).ext.participant("b") is not None for r in d_tasks
        )


async def test_a_parked_sub_task_on_agent_b_pushes_to_agent_as_prefixed_route(
    tmp_path: Path,
) -> None:
    """
    Requirement: docs/specs/issue-36/requirements.md#R6

    Scenario: A parked sub-task on agent b pushes to agent a's prefixed route
        Given agent a delegated a sub-task to agent b, and b parked it asking a a question
        When a's stand-in registers a push config on b's task
        Then the push URL is a's prefixed push route
        And when a third party cancels b's task, b's push wakes a's stand-in
        And a's sub-task ends CANCELED
    """
    scripts = {
        "a": [
            scripted("", tool_calls=[delegate("b", "Check the refund.")]),
            scripted("Asking billing."),
            scripted("Noted."),
            scripted("Noted again."),
        ],
        "b": [scripted("", tool_calls=[ask_back("a", "Which order?")])],
    }
    async with five_agents(tmp_path, scripts, starlette_example.build_app) as service:
        first = await ask(f"{service.origin}/agents/a", "Refund my order.")
        await service.until("a", first.id, sub_task_state("INPUT_REQUIRED"))
        b_store = service.harnesses["b"]._activities.engine.store  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
        configs: list[PushConfigRecord] = []
        for _ in range(400):
            configs = list(await b_store.query(PushConfigRecord, Filter()))
            if configs:
                break
            await asyncio.sleep(0.05)
        assert configs, "a's stand-in never registered a push config on b's task"
        url = configs[0].url
        assert re.fullmatch(re.escape(f"{service.origin}/agents/a/a2a/push/") + r"[^/]+", url), url
        b_task = configs[0].task_id
        await (
            service.harnesses["b"]
            .client.get_workflow_handle(b_task)
            .signal("cancel", "stopped by the operator")
        )
        parent = await service.until("a", first.id, sub_task_state("CANCELED"))
        assert parent.ext.sub_tasks[0].state == TaskState.Name(
            TaskState.TASK_STATE_CANCELED
        ).removeprefix("TASK_STATE_")
