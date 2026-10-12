"""``follow_remote_task`` (issue-27 R3): the window bounds an open stream, a stream that
ends unchanged is re-opened no faster than ``follow_interval``, and an agent that is not a
remote one is a non-retryable failure."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from typing import cast

import pytest
from a2a.client.client import Client as A2AClient
from a2a.types import AgentCapabilities, AgentCard, Task, TaskState, TaskStatus
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from tests.integration.durable.conftest import Harness
from tiny_harness.harness.agents import A2AEvent, RemoteAgent
from tiny_harness.harness.entities import EntityKind, EntityRef, RegistryEntry
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.models import FollowIn

PARKED = Task(id="r-1", status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED))


class Peer(RemoteAgent):
    """A remote agent whose stream the test scripts: ``hold`` keeps it open unchanged."""

    def __init__(self, *, hold: bool, interval: timedelta) -> None:
        card = AgentCard(name="peer", capabilities=AgentCapabilities(push_notifications=False))
        super().__init__(
            EntityRef(kind=EntityKind.AGENT, id="peer", version=None),
            card,
            client=cast(A2AClient, None),
            follow_interval=interval,
        )
        self.hold = hold
        self.opened: list[float] = []

    async def subscribe(
        self, task_id: str, *, extensions: Sequence[str] = (), participant: str | None = None
    ) -> AsyncIterator[A2AEvent]:
        self.opened.append(time.monotonic())
        yield PARKED
        if self.hold:
            await asyncio.sleep(3600)


async def activities(peer: RemoteAgent | None, window: float) -> Activities:
    h = await Harness([]).bind()
    if peer is not None:
        await h.registry.add(RegistryEntry(ref=peer.ref, instance=peer))
    acts = Activities(h.engine)
    acts.follow_window = timedelta(seconds=window)
    acts.heartbeat_every = 0.05
    return acts


def follow_in(agent: str = "peer") -> FollowIn:
    return FollowIn(
        task_id="t-1.1",
        correlation_id="c",
        agent=agent,
        remote_task_id="r-1",
        known_state="INPUT_REQUIRED",
    )


async def test_the_window_bounds_a_stream_that_stays_open() -> None:
    peer = Peer(hold=True, interval=timedelta(seconds=1))
    acts = await activities(peer, window=0.4)
    started = time.monotonic()
    out = await ActivityEnvironment().run(acts.follow_remote_task, follow_in())
    assert out.changed is False
    assert time.monotonic() - started < 2.0
    assert len(peer.opened) == 1


async def test_a_stream_that_ends_unchanged_is_reopened_at_the_interval() -> None:
    peer = Peer(hold=False, interval=timedelta(seconds=1))
    acts = await activities(peer, window=2.5)
    out = await ActivityEnvironment().run(acts.follow_remote_task, follow_in())
    assert out.changed is False
    gaps = [b - a for a, b in zip(peer.opened, peer.opened[1:], strict=False)]
    assert 2 <= len(peer.opened) <= 3
    assert all(gap >= 0.9 for gap in gaps), gaps


async def test_an_agent_that_is_not_remote_is_not_followed() -> None:
    acts = await activities(None, window=1)
    with pytest.raises(ApplicationError) as info:
        await ActivityEnvironment().run(acts.follow_remote_task, follow_in("missing"))
    assert info.value.non_retryable
