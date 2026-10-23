"""Media bytes per model request (issue-38 R1.6, self-review 2.1): ``resolve_media`` sends
the newest media first within ``[media] max_request_media_bytes``; an older image that
does not fit, and an image larger than the adapter's ``max_image_bytes``, become a line
of text instead of bytes."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore, MediaAttachment, MediaRef
from tiny_harness.harness.media.render import resolve_media
from tiny_harness.harness.models import (
    AnthropicLLM,
    LLMModelInfo,
    LLMRequest,
    MessageItem,
    OpenAILLM,
    Role,
)

INFO = LLMModelInfo(
    provider="fake",
    model="m",
    context_window_tokens=128_000,
    input_modalities=frozenset({"text", "image"}),
)


@pytest.fixture
def store(tmp_path: Path) -> FileMediaStore:
    return FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), tmp_path / "media")


async def _image(store: FileMediaStore, name: str, size: int) -> MediaRef:
    return await store.put("t-1", b"x" * size, media_type="image/png", name=name)


def _request(*refs: MediaRef) -> LLMRequest:
    return LLMRequest(
        instructions="sys",
        input=tuple(
            MessageItem(role=Role.USER, text=f"turn {n}", media=(MediaAttachment(ref=ref),))
            for n, ref in enumerate(refs)
        ),
    )


def _sent(request: LLMRequest) -> list[tuple[str, bool]]:
    return [
        (attachment.ref.name, attachment.data is not None)
        for item in request.input
        if isinstance(item, MessageItem)
        for attachment in item.media
    ]


def _texts(request: LLMRequest) -> list[str]:
    return [item.text for item in request.input if isinstance(item, MessageItem)]


async def test_the_newest_images_fill_the_budget_first(store: FileMediaStore) -> None:
    old = await _image(store, "old.png", 400)
    mid = await _image(store, "mid.png", 400)
    new = await _image(store, "new.png", 400)
    out = await resolve_media(_request(old, mid, new), store, INFO, max_bytes=900)
    assert _sent(out) == [("mid.png", True), ("new.png", True)]
    assert _texts(out) == ["turn 0\n[image old.png shown earlier, not re-sent]", "turn 1", "turn 2"]


async def test_without_a_budget_every_image_is_sent(store: FileMediaStore) -> None:
    refs = [await _image(store, f"{n}.png", 400) for n in range(3)]
    out = await resolve_media(_request(*refs), store, INFO)
    assert [sent for _, sent in _sent(out)] == [True, True, True]


async def test_an_image_over_the_model_cap_is_not_sent(store: FileMediaStore) -> None:
    info = INFO.model_copy(update={"max_image_bytes": 1_000})
    small = await _image(store, "small.png", 600)  # 800 bytes as base64
    big = await _image(store, "big.png", 900)  # 1 200 bytes as base64
    out = await resolve_media(_request(small, big), store, info)
    assert _sent(out) == [("small.png", True)]
    assert _texts(out)[1] == "turn 1\n[image big.png too large for this model]"


def test_each_adapter_declares_its_image_cap() -> None:
    anthropic = AnthropicLLM(SecretStr("k"), model="claude-opus-5-5")
    assert anthropic.info.max_image_bytes == 5_242_880
    assert OpenAILLM(SecretStr("k")).info.max_image_bytes is None
