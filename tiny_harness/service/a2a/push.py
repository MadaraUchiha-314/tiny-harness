"""Push notification configs (R15.6) in the store, and the sink the ``emit_event``
activity delivers through. The client's credential is kept as supplied; protecting it at
rest is the store's job (issue-23).

The inbound half (issue-27): ``PushReceiver`` answers ``POST /a2a/push/{task_id}``, the
URL a remote task's stand-in registers. A push is only a doorbell: once the presented
token's digest matches, the stand-in fetches the remote task itself, so nothing in the
body is ever applied (abuse case 6)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

import httpx
from a2a.server.context import ServerCallContext
from a2a.server.tasks import BasePushNotificationSender, PushNotificationConfigStore
from a2a.types import (
    AuthenticationInfo,
    StreamResponse,
    Task,
    TaskPushNotificationConfig,
    TaskStatusUpdateEvent,
)
from google.protobuf import json_format
from pydantic import SecretStr
from temporalio.client import Client

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.persistence import Filter, PushConfigRecord, Store
from tiny_harness.service.durable.activities import remote_out, sub_state_of
from tiny_harness.service.durable.models import EventEntry, PushIn, entry_event
from tiny_harness.service.push_token import push_url, token_digest

log = logging.getLogger(__name__)

PUSH_PATH: Final = "/a2a/push/{task_id}"
PUSH_TOKEN_HEADER: Final = "X-A2A-Notification-Token"
MAX_PUSH_BYTES: Final = 65_536
"""A push carries one task or status event; anything larger is refused (abuse case 5)."""


class StorePushConfigStore(PushNotificationConfigStore):
    def __init__(self, store: Store) -> None:
        self._store = store

    async def set_info(
        self,
        task_id: str,
        notification_config: TaskPushNotificationConfig,
        context: ServerCallContext | None = None,
    ) -> TaskPushNotificationConfig | None:
        config_id = notification_config.id or uuid.uuid4().hex
        auth = ""
        if notification_config.HasField("authentication"):
            auth = json_format.MessageToJson(notification_config.authentication)
        await self._store.put(
            PushConfigRecord(
                id=f"{task_id}:{config_id}",
                context_id="",
                task_id=task_id,
                created_at=datetime.now(UTC),
                config_id=config_id,
                url=notification_config.url,
                token=SecretStr(notification_config.token),
                authentication=SecretStr(auth),
            )
        )
        record = await self._store.get(PushConfigRecord, f"{task_id}:{config_id}")
        live = await self._live([record] if record is not None else [])
        return live[0] if live else None

    async def _live(self, records: Sequence[PushConfigRecord]) -> list[TaskPushNotificationConfig]:
        """Decode the records; drop a row an earlier version stored encrypted under the
        removed ``TINY_HARNESS_PUSH_KEY`` — never deliver it (issue-23 R4)."""
        configs: list[TaskPushNotificationConfig] = []
        for record in records:
            if record.legacy:
                await self._store.delete(PushConfigRecord, record.id)
                log.warning(
                    "push config %s for task %s was stored encrypted by an earlier version; "
                    "dropped, the client must register it again",
                    record.config_id,
                    record.task_id,
                )
                continue
            config = TaskPushNotificationConfig(
                id=record.config_id, task_id=record.task_id, url=record.url
            )
            if token := record.token.get_secret_value():
                config.token = token
            if auth := record.authentication.get_secret_value():
                json_format.Parse(auth, config.authentication)
            configs.append(config)
        return configs

    async def get_info(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> list[TaskPushNotificationConfig]:
        return await self.get_info_for_dispatch(task_id)

    async def get_info_for_dispatch(self, task_id: str) -> list[TaskPushNotificationConfig]:
        return await self._live(await self._store.query(PushConfigRecord, Filter(task_id=task_id)))

    async def delete_info(
        self,
        task_id: str,
        context: ServerCallContext | None = None,
        config_id: str | None = None,
    ) -> None:
        if config_id:
            await self._store.delete(PushConfigRecord, f"{task_id}:{config_id}")
            return
        for record in await self._store.query(PushConfigRecord, Filter(task_id=task_id)):
            await self._store.delete(PushConfigRecord, record.id)


class PushSink:
    """The ``emit_event`` activity's sink: reads the configs and posts the event (R15.6)."""

    def __init__(
        self, store: StorePushConfigStore, client: httpx.AsyncClient | None = None
    ) -> None:
        self._store = store
        self._sender = BasePushNotificationSender(client or httpx.AsyncClient(timeout=10), store)

    async def deliver(self, task_id: str, context_id: str, entry: EventEntry) -> None:
        if entry.kind == "message":
            return  # push notifications carry task state, not conversation messages
        event: A2AEvent = entry_event(entry)
        await self._sender.send_notification(task_id, event)  # type: ignore[arg-type]


def _claimed_state(response: StreamResponse) -> str:
    """The state a push says the task is in, mapped as a turn's end is (issue-27 R2.5)."""
    if response.HasField("task"):
        event: Task | TaskStatusUpdateEvent = response.task
    elif response.HasField("status_update"):
        event = response.status_update
    else:
        return ""
    if not event.HasField("status"):
        return ""
    return remote_out("", event.status.state, sub_state_of(event.metadata), None).state_name


def _remote_task_id(response: StreamResponse) -> str:
    if response.HasField("task"):
        return response.task.id
    if response.HasField("status_update"):
        return response.status_update.task_id
    if response.HasField("artifact_update"):
        return response.artifact_update.task_id
    if response.HasField("message"):
        return response.message.task_id
    return ""


class PushReceiver:
    """Verifies an inbound push and wakes its stand-in (issue-27 R2.1, R2.2).

    The checks run cheapest first, and only a push that has a token and a parseable body
    reaches Temporal. There the ``remote_push`` update's validator compares digests in
    constant time. Every refusal past the parse step is the same ``401``, whether the token
    is wrong, the id names no stand-in, or the stand-in has ended (abuse cases 1, 2, 4)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def receive(self, task_id: str, token: str | None, body: bytes) -> int:
        if len(body) > MAX_PUSH_BYTES:
            log.info("push for %s refused: too large", task_id)
            return 413
        if not token:
            log.info("push for %s refused: no token", task_id)
            return 401
        response = StreamResponse()
        try:
            json_format.Parse(body, response, ignore_unknown_fields=True)
        except json_format.ParseError, ValueError:
            log.info("push for %s refused: unparseable body", task_id)
            return 400
        remote_task_id = _remote_task_id(response)
        if not remote_task_id:
            log.info("push for %s refused: no task id", task_id)
            return 400
        handle = self._client.get_workflow_handle(task_id)
        try:
            await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
                "remote_push",
                PushIn(
                    token_digest=token_digest(token),
                    remote_task_id=remote_task_id,
                    claimed_state=_claimed_state(response),
                ),
            )
        except Exception:  # any failure is a refusal, and says nothing about why
            log.info("push for %s refused: not accepted", task_id)
            return 401
        return 204


__all__ = [
    "MAX_PUSH_BYTES",
    "PUSH_PATH",
    "PUSH_TOKEN_HEADER",
    "AuthenticationInfo",
    "PushReceiver",
    "PushSink",
    "StorePushConfigStore",
    "push_url",
    "token_digest",
]
