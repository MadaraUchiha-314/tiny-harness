"""The agents the roster lists: one per id, the version a delegation reaches (issue-34)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from a2a.types import AgentCard, Message, Task

from tiny_harness.harness.agents import A2AEvent, Agent
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.service.runtime import registered_agents


class IdleAgent(Agent):
    def __init__(self, agent_id: str, version: str | None, description: str) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.AGENT, id=agent_id, version=version),
            AgentCard(name=agent_id, description=description),
        )

    async def send_message(
        self, request: Message, *, extensions: Sequence[str] = ()
    ) -> AsyncIterator[A2AEvent]:
        raise AssertionError("not called")
        yield  # pragma: no cover

    async def cancel_task(self, task_id: str) -> Task:
        raise AssertionError("not called")


async def test_an_agent_at_two_versions_is_listed_once_at_its_latest() -> None:
    registry = Registry()
    for agent in (
        IdleAgent("ledger", "1.0.0", "old card"),
        IdleAgent("ledger", "2.0.0", "new card"),
        IdleAgent("audit", None, "unversioned"),
    ):
        await registry.add(RegistryEntry(ref=agent.ref, instance=agent))
    agents = await registered_agents(registry)
    assert [(a.ref.id, a.agent_card.description) for a in agents] == [
        ("audit", "unversioned"),
        ("ledger", "new card"),
    ]
