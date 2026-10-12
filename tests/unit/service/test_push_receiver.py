"""The push endpoint's receiver (issue-27 R2.1, R2.2; abuse cases 1, 2, 5, 9): refusal
ordering over a fake Temporal client, the URL it registers, and the token digest."""

from __future__ import annotations

import hashlib
import json
from typing import cast

import pytest
from temporalio.client import Client

from tiny_harness.service.a2a.push import (
    MAX_PUSH_BYTES,
    PushReceiver,
    push_url,
    token_digest,
)
from tiny_harness.service.durable.models import PushIn

TOKEN = "t0ken-" + "x" * 40
BODY = json.dumps(
    {"statusUpdate": {"taskId": "remote-1", "status": {"state": "TASK_STATE_CANCELED"}}}
).encode()


class FakeHandle:
    def __init__(self, client: FakeClient, workflow_id: str) -> None:
        self.client = client
        self.workflow_id = workflow_id

    async def execute_update(self, name: str, arg: PushIn) -> None:
        self.client.updates.append((self.workflow_id, name, arg))
        if self.client.fail:
            raise RuntimeError("update rejected")


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.updates: list[tuple[str, str, PushIn]] = []

    def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
        return FakeHandle(self, workflow_id)


def receiver(fake: FakeClient) -> PushReceiver:
    return PushReceiver(cast(Client, fake))


async def test_a_push_with_a_token_wakes_its_stand_in_with_the_digest() -> None:
    fake = FakeClient()
    assert await receiver(fake).receive("t-1.1", TOKEN, BODY) == 204
    ((workflow_id, name, arg),) = fake.updates
    assert (workflow_id, name) == ("t-1.1", "remote_push")
    assert arg == PushIn(
        token_digest=token_digest(TOKEN), remote_task_id="remote-1", claimed_state="CANCELED"
    )
    assert TOKEN not in arg.model_dump_json()


@pytest.mark.parametrize("token", [None, ""])
async def test_a_push_without_a_token_is_refused_before_temporal(token: str | None) -> None:
    fake = FakeClient()
    assert await receiver(fake).receive("t-1.1", token, BODY) == 401
    assert fake.updates == []


async def test_an_oversized_push_is_refused_before_anything_else() -> None:
    fake = FakeClient()
    assert await receiver(fake).receive("t-1.1", None, b"x" * (MAX_PUSH_BYTES + 1)) == 413
    assert fake.updates == []


@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"statusUpdate": {"status": {}}}'])
async def test_a_malformed_push_is_a_bad_request(body: bytes) -> None:
    fake = FakeClient()
    assert await receiver(fake).receive("t-1.1", TOKEN, body) == 400
    assert fake.updates == []


async def test_a_rejected_update_answers_as_a_wrong_token() -> None:
    fake = FakeClient(fail=True)
    assert await receiver(fake).receive("t-1.1", TOKEN, BODY) == 401


@pytest.mark.parametrize(
    "body",
    [
        {"task": {"id": "remote-1", "status": {"state": "TASK_STATE_WORKING"}}},
        {"artifactUpdate": {"taskId": "remote-1"}},
        {"message": {"taskId": "remote-1", "messageId": "m", "role": "ROLE_AGENT"}},
    ],
)
async def test_every_stream_response_kind_names_its_task(body: dict[str, object]) -> None:
    fake = FakeClient()
    assert await receiver(fake).receive("t-1.1", TOKEN, json.dumps(body).encode()) == 204
    assert fake.updates[0][2].remote_task_id == "remote-1"


def test_the_digest_is_sha256_hex() -> None:
    assert token_digest(TOKEN) == hashlib.sha256(TOKEN.encode()).hexdigest()


@pytest.mark.parametrize("base", ["http://harness.example", "http://harness.example/"])
def test_the_push_url_is_the_base_url_and_the_local_id(base: str) -> None:
    assert push_url(base, "t-1.1") == "http://harness.example/a2a/push/t-1.1"


def test_the_push_url_encodes_the_local_id() -> None:
    assert push_url("http://h", "a/b?c") == "http://h/a2a/push/a%2Fb%3Fc"
