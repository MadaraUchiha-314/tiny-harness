"""Push notification configs (R15.6) in the store, and the sink the ``emit_event``
activity delivers through. The client's credential is kept as supplied; protecting it at
rest is the store's job (issue-23)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx
from a2a.server.context import ServerCallContext
from a2a.server.tasks import BasePushNotificationSender, PushNotificationConfigStore
from a2a.types import AuthenticationInfo, TaskPushNotificationConfig
from google.protobuf import json_format
from pydantic import SecretStr

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.persistence import Filter, PushConfigRecord, Store
from tiny_harness.service.durable.models import EventEntry, entry_event

log = logging.getLogger(__name__)


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


__all__ = ["AuthenticationInfo", "PushSink", "StorePushConfigStore"]
