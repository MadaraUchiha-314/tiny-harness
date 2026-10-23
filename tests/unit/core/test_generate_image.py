"""The ``generate_image`` intrinsic's body and its agent note (issue-38 R2.1, R2.5)."""

from __future__ import annotations

from pathlib import Path

from tiny_harness.errors import ProviderError
from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.core.intrinsics import GenerateImageTool, TaskContext, image_intrinsic
from tiny_harness.harness.core.loop import media_notes
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore
from tiny_harness.harness.models import FakeImageGenerator
from tiny_harness.harness.tools import ToolCall, ToolResult


def task() -> HarnessTask:
    return HarnessTask.new(
        "t-1",
        "ctx-1",
        TaskExtensionData(
            name="Draw",
            goal="Draw",
            participants=(Participant(id="alice", kind="human", role=Role.REPORTER),),
        ),
    )


def store(root: Path) -> FileMediaStore:
    return FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), root)


def call(**arguments: str) -> ToolCall:
    return ToolCall(
        call_id="c1",
        name="generate_image",
        arguments={"prompt": "a sofa", "alt": "A green sofa", **arguments},
    )


async def test_the_image_is_stored_and_returned_as_a_media_part(tmp_path: Path) -> None:
    media = store(tmp_path)
    tool = GenerateImageTool(TaskContext(task()), FakeImageGenerator(), media)
    result = await tool.invoke(call())
    assert isinstance(result, ToolResult) and not result.is_error
    text, part = result.content
    assert part.kind == "media" and part.media is not None and part.text == "A green sofa"
    assert text.text == f"image {part.media.id} shown to the user"
    assert part.media.name == "a-green-sofa.png"
    assert (part.media.width, part.media.height) == (1024, 1024)
    assert await media.lookup("t-1", part.media.id) == part.media


async def test_a_provider_refusal_is_an_error_result_and_nothing_is_stored(
    tmp_path: Path,
) -> None:
    refused = ProviderError("content policy", provider="fake", status=400)
    tool = GenerateImageTool(TaskContext(task()), FakeImageGenerator([refused]), store(tmp_path))
    result = await tool.invoke(call())
    assert isinstance(result, ToolResult) and result.is_error
    assert not any(tmp_path.iterdir())


def test_no_tool_without_a_generator_or_a_store(tmp_path: Path) -> None:
    context = TaskContext()
    assert image_intrinsic(context, None, store(tmp_path)) == ()
    assert image_intrinsic(context, FakeImageGenerator(), None) == ()
    [tool] = image_intrinsic(context, FakeImageGenerator(), store(tmp_path))
    assert tool.definition.name == "generate_image"


async def test_a_media_part_becomes_an_agent_note_with_the_image(tmp_path: Path) -> None:
    tool = GenerateImageTool(TaskContext(task()), FakeImageGenerator(), store(tmp_path))
    result = await tool.invoke(call())
    assert isinstance(result, ToolResult)
    [note] = media_notes(result)
    assert note.source == "agent" and note.text == "[image generated: A green sofa]"
    assert [a.ref for a in note.media] == [result.content[1].media]
    assert media_notes(ToolResult.text("c2", "plain")) == []
