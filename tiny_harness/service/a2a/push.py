"""Push notification configs (R15.6) in the store, tokens encrypted at rest (finding 1),
and the sink the ``emit_event`` activity delivers through."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from a2a.server.context import ServerCallContext
from a2a.server.tasks import BasePushNotificationSender, PushNotificationConfigStore
from a2a.types import AuthenticationInfo, TaskPushNotificationConfig
from google.protobuf import json_format

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.persistence import Filter, PushConfigRecord, PushTokenCipher, Store
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.durable.models import EventEntry, entry_event


class StorePushConfigStore(PushNotificationConfigStore):
    def __init__(self, store: Store, cipher: PushTokenCipher) -> None:
        self._store = store
        self._cipher = cipher

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
                token_ciphertext=self._cipher.encrypt(notification_config.token)
                if notification_config.token
                else "",
                authentication_ciphertext=self._cipher.encrypt(auth) if auth else "",
            )
        )
        return self._decode(await self._store.get(PushConfigRecord, f"{task_id}:{config_id}"))

    def _decode(self, record: PushConfigRecord | None) -> TaskPushNotificationConfig | None:
        if record is None:
            return None
        config = TaskPushNotificationConfig(
            id=record.config_id, task_id=record.task_id, url=record.url
        )
        if record.token_ciphertext:
            config.token = self._cipher.decrypt(record.token_ciphertext)
        if record.authentication_ciphertext:
            json_format.Parse(
                self._cipher.decrypt(record.authentication_ciphertext), config.authentication
            )
        return config

    async def get_info(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> list[TaskPushNotificationConfig]:
        return await self.get_info_for_dispatch(task_id)

    async def get_info_for_dispatch(self, task_id: str) -> list[TaskPushNotificationConfig]:
        records = await self._store.query(PushConfigRecord, Filter(task_id=task_id))
        return [c for c in (self._decode(r) for r in records) if c is not None]

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
    """The ``emit_event`` activity's sink: decrypts the config and posts the event (R15.6)."""

    def __init__(
        self, store: StorePushConfigStore, client: httpx.AsyncClient | None = None
    ) -> None:
        self._store = store
        self._sender = BasePushNotificationSender(client or httpx.AsyncClient(timeout=10), store)

    async def deliver(self, task_id: str, context_id: str, entry_payload: object) -> None:
        if not isinstance(entry_payload, dict):
            return
        payload: JsonObject = entry_payload  # type: ignore[assignment]
        kind = "status_update" if "status" in payload and "taskId" in payload else "task"
        entry = EventEntry(seq=0, kind=kind, payload=payload)  # type: ignore[arg-type]
        event: A2AEvent = entry_event(entry)
        await self._sender.send_notification(task_id, event)  # type: ignore[arg-type]


__all__ = ["AuthenticationInfo", "PushSink", "StorePushConfigStore"]
