"""The persistence store (R11.1-R11.4) and retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from a2a.types import Task, TaskState, TaskStatus

from tiny_harness.errors import StoreWriteError
from tiny_harness.harness.core import AgentState, Plan, SchemaValidated, Step
from tiny_harness.harness.persistence import (
    ChannelMessageRecord,
    Filter,
    InboxAuditRecord,
    PlanRecord,
    RecordKind,
    SqliteStore,
    StateRecord,
    TaskRecord,
)
from tiny_harness.harness.tools import ContentPart

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def task_record(id: str = "t-1", at: datetime = NOW) -> TaskRecord:
    proto = Task(id=id, context_id="ctx", status=TaskStatus(state=TaskState.TASK_STATE_WORKING))
    return TaskRecord(
        id=id, context_id="ctx", task_id=id, created_at=at, task=proto, state_name="WORKING"
    )


async def test_put_get_query_round_trip_including_the_proto(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "s.sqlite3")
    await store.put(task_record())
    got = await store.get(TaskRecord, "t-1")
    assert (
        got is not None
        and got.task.id == "t-1"
        and got.task.status.state == TaskState.TASK_STATE_WORKING
    )
    await store.put(
        PlanRecord(
            id="t-1:1",
            context_id="ctx",
            task_id="t-1",
            created_at=NOW,
            turn=1,
            plan=Plan(steps=(Step(id="a", name="a"),)),
        )
    )
    state = AgentState(task_id="t-1", summary="so far").model_copy(
        update={"data": SchemaValidated().write("x", 1)}
    )
    await store.put(StateRecord.from_state(state, context_id="ctx", at=NOW))
    plans = await store.query(PlanRecord, Filter(task_id="t-1"))
    assert [p.id for p in plans] == ["t-1:1"]
    states = await store.query(StateRecord, Filter(context_id="ctx"))
    assert states[0].summary == "so far" and states[0].data.read("x") == 1
    assert await store.get(TaskRecord, "missing") is None
    store.close()


async def test_query_filters_by_time_and_limits(tmp_path: Path) -> None:
    store = SqliteStore(":memory:")
    for i in range(5):
        await store.put(
            InboxAuditRecord(
                id=f"m{i}",
                context_id="ctx",
                task_id="t-1",
                created_at=NOW + timedelta(minutes=i),
                message_id=f"m{i}",
                participant_id="u-1",
                accepted=True,
            )
        )
    rows = await store.query(InboxAuditRecord, Filter(since=NOW + timedelta(minutes=1), limit=2))
    assert [r.id for r in rows] == ["m2", "m3"]


async def test_write_failure_surfaces_store_write_error(tmp_path: Path) -> None:
    store = SqliteStore(":memory:")
    store.close()
    with pytest.raises(StoreWriteError):
        await store.put(task_record())


async def test_sweep_deletes_expired_rows_per_kind() -> None:
    store = SqliteStore(":memory:")
    await store.put(task_record("old", NOW - timedelta(days=40)))
    await store.put(task_record("new", NOW - timedelta(days=1)))
    await store.put(
        ChannelMessageRecord(
            id="c1",
            context_id="ctx",
            task_id="old",
            created_at=NOW - timedelta(days=40),
            channel_id="ch",
            sender="u-1",
            message_kind="message",
            parts=(ContentPart(kind="text", text="hi"),),
        )
    )
    deleted = await store.sweep(
        {RecordKind.TASKS: timedelta(days=30), RecordKind.CHANNEL_MESSAGES: timedelta(days=90)}, NOW
    )
    assert deleted[RecordKind.TASKS] == 1 and deleted[RecordKind.CHANNEL_MESSAGES] == 0
    assert (
        await store.get(TaskRecord, "old") is None
        and await store.get(TaskRecord, "new") is not None
    )
    purged = await store.purge_task("old")
    assert purged[RecordKind.CHANNEL_MESSAGES] == 1


def test_no_record_has_a_credential_field() -> None:
    from tiny_harness.harness.persistence import RECORD_TYPES

    for record_type in RECORD_TYPES.values():
        for name in record_type.model_fields:
            assert not any(s in name for s in ("secret", "password", "api_key")), name
            # the only token-shaped field is ciphertext by construction
            assert "token" not in name or name.endswith("_ciphertext"), name
