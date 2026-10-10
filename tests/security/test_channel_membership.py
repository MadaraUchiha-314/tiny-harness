"""Abuse case 4: a non-member is refused with the same error as an unknown sender."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tiny_harness.errors import ChannelMembershipError
from tiny_harness.harness.channels import A2AChannel, ChannelMessage
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.persistence import ChannelMessageRecord, Filter, SqliteStore
from tiny_harness.harness.tools import ContentPart


async def test_non_member_rejected_without_task_existence() -> None:
    store = SqliteStore(":memory:")

    async def emit(m: ChannelMessage) -> None:
        raise AssertionError("nothing is emitted for a refused message")

    channel = A2AChannel(
        EntityRef(kind=EntityKind.CHANNEL, id="task-7f3a"),
        task_id="t-1",
        context_id="ctx-1",
        members=["u-1"],
        store=store,
        emitter=emit,
    )
    errors: list[str] = []
    for sender in ("stranger", "", None):
        msg = ChannelMessage(
            id="m1",
            channel_id="task-7f3a",
            sender=sender or "",
            parts=(ContentPart(kind="text", text="hi"),),
            at=datetime(2026, 10, 9, tzinfo=UTC),
        )
        with pytest.raises(ChannelMembershipError) as info:
            await channel.accept(msg)
        errors.append(str(info.value))
    assert len(set(errors)) == 1, "one uniform error, revealing nothing about the task"
    assert "t-1" not in errors[0] and "u-1" not in errors[0]
    assert await store.query(ChannelMessageRecord, Filter(task_id="t-1")) == []
