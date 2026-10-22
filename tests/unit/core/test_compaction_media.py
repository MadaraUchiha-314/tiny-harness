"""Compaction with media (issue-38 R6.2, design critic 7): the summarise request carries
the folded media the model can take, the rest is rendered as text, native audio is
transcribed first where speech-to-text exists, and the summary names every folded media
item, with a fallback line for any the model left out."""

from __future__ import annotations

from pathlib import Path

from tiny_harness.harness.core import (
    AgentState,
    ContextWindowManager,
    HarnessTask,
    Participant,
    Role,
    TaskExtensionData,
)
from tiny_harness.harness.core.compaction import (
    SUMMARISE,
    CompactionMedia,
    CompactionSummariseIn,
    Compactor,
)
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookManager, HookPoint
from tiny_harness.harness.media import FileMediaStore, MediaAttachment, MediaKind, MediaRef
from tiny_harness.harness.models import (
    FakeLLM,
    FakeSpeechToText,
    LLMModelInfo,
    MessageItem,
    Modality,
    scripted,
)
from tiny_harness.harness.models import Role as MessageRole
from tiny_harness.harness.models.speech import SpeechToText
from tiny_harness.harness.tools import ContentPart, ToolResult


def png(width: int = 4, height: int = 4) -> bytes:
    from tests.fixtures import media as fx

    return fx.png(width, height)


def wav() -> bytes:
    from tests.fixtures import media as fx

    return fx.wav(seconds=2)


def task() -> HarnessTask:
    return HarnessTask.new(
        "t-1",
        "ctx",
        TaskExtensionData(
            name="n",
            goal="g",
            participants=(Participant(id="a", kind="human", role=Role.REPORTER),),
        ),
    )


def info(
    modalities: frozenset[Modality] = frozenset({"text", "image"}),
    audio_formats: frozenset[str] = frozenset(),
) -> LLMModelInfo:
    return LLMModelInfo(
        provider="fake",
        model="fake-1",
        context_window_tokens=100_000,
        input_modalities=modalities,
        audio_input_formats=audio_formats,
    )


async def stored(root: Path) -> tuple[FileMediaStore, MediaRef, MediaRef, bytes, bytes]:
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), root)
    image, audio = png(), wav()
    photo = await store.put(
        "t-1", image, media_type="image/png", name="photo.png", width=4, height=4
    )
    memo = await store.put("t-1", audio, media_type="audio/wav", name="memo.wav", duration_ms=2_000)
    return store, photo, memo, image, audio


def history(*media: MediaAttachment) -> AgentState:
    """Four entries; the first two fold: a user message with ``media``, and a reply."""
    return (
        AgentState(task_id="t-1")
        .append(MessageItem(role=MessageRole.USER, text="look at these", media=media))
        .append(MessageItem(role=MessageRole.ASSISTANT, text="I see them."))
        .append(MessageItem(role=MessageRole.USER, text="and now?"))
        .append(MessageItem(role=MessageRole.ASSISTANT, text="Still here."))
    )


async def compact(
    state: AgentState,
    llm: FakeLLM,
    store: FileMediaStore | None,
    model: LLMModelInfo,
    stt: SpeechToText | None = None,
    hooks: HookManager | None = None,
) -> AgentState:
    hooks = hooks or HookManager()
    manager = ContextWindowManager()
    media = None
    if store is not None:
        media = CompactionMedia(store=store, model_info=lambda _: model, speech_to_text=stt)
    compactor = Compactor(hooks=hooks, manager=manager, llm=llm, media=media)
    compactor.register_defaults()
    window = manager.assemble(
        task=task(), state=state, system_prompt="S", skills_index="", tools=()
    )
    new_state, record = await compactor.compact(state, window, task_id="t-1", correlation_id="c")
    assert record.summary == new_state.summary
    return new_state


def summarise_request(llm: FakeLLM) -> MessageItem:
    [request] = llm.requests
    [item] = request.input
    assert isinstance(item, MessageItem)
    return item


async def test_the_summary_request_carries_the_images_the_model_takes(tmp_path: Path) -> None:
    store, photo, _, image, _ = await stored(tmp_path)
    line = f'[image {photo.id} "photo.png": a grey cat on a sofa]'
    llm = FakeLLM([scripted(f"Alice sent a photo.\n{line}")])
    state = await compact(history(MediaAttachment(ref=photo)), llm, store, info())
    item = summarise_request(llm)
    [attachment] = item.media
    assert attachment.ref == photo and attachment.data == image
    assert f'image {photo.id} "photo.png"' in item.text
    [request] = llm.requests
    assert '[image <id> "<name>": <one-sentence description>]' in request.instructions
    assert state.summary == f"Alice sent a photo.\n{line}"  # present: nothing appended


async def test_a_missing_line_is_appended_as_not_described(tmp_path: Path) -> None:
    store, photo, _, _, _ = await stored(tmp_path)
    llm = FakeLLM([scripted("Alice sent a photo.")])
    state = await compact(history(MediaAttachment(ref=photo)), llm, store, info())
    assert state.summary == f'Alice sent a photo.\n[image {photo.id} "photo.png": not described]'


async def test_media_the_model_cannot_take_is_rendered_as_text(tmp_path: Path) -> None:
    store, photo, memo, _, _ = await stored(tmp_path)
    llm = FakeLLM([scripted("Two files.")])
    folded = (MediaAttachment(ref=photo), MediaAttachment(ref=memo, transcript="buy milk"))
    state = await compact(history(*folded), llm, store, info(frozenset({"text"})))
    item = summarise_request(llm)
    assert item.media == ()
    assert f"[image: photo.png, 4\N{MULTIPLICATION SIGN}4, media {photo.id}]" in item.text
    assert '[audio: memo.wav, 2 s, transcript: "buy milk"]' in item.text
    assert state.summary.splitlines()[1:] == [
        f'[image {photo.id} "photo.png": not described]',
        f'[audio {memo.id} "memo.wav": buy milk]',
    ]


async def test_native_audio_without_a_transcript_is_transcribed_first(tmp_path: Path) -> None:
    store, _, memo, _, audio = await stored(tmp_path)
    stt = FakeSpeechToText(["call the plumber"])
    llm = FakeLLM([scripted(f'[audio {memo.id} "memo.wav": call the plumber]')])
    native = info(frozenset({"text", "audio"}), frozenset({"audio/wav"}))
    await compact(history(MediaAttachment(ref=memo)), llm, store, native, stt=stt)
    [call] = stt.calls
    assert call.audio == audio
    item = summarise_request(llm)
    assert item.media == ()
    assert '[audio: memo.wav, 2 s, transcript: "call the plumber"]' in item.text


async def test_native_audio_goes_to_a_model_that_takes_it_when_there_is_no_stt(
    tmp_path: Path,
) -> None:
    store, _, memo, _, audio = await stored(tmp_path)
    llm = FakeLLM([scripted("A voice memo.")])
    native = info(frozenset({"text", "audio"}), frozenset({"audio/wav"}))
    state = await compact(history(MediaAttachment(ref=memo)), llm, store, native)
    [attachment] = summarise_request(llm).media
    assert attachment.data == audio
    assert state.summary.endswith(f'[audio {memo.id} "memo.wav": not described]')


async def test_a_generated_image_in_an_agent_note_is_named_too(tmp_path: Path) -> None:
    store, photo, _, _, _ = await stored(tmp_path)
    note = MessageItem(
        role=MessageRole.USER,
        source="agent",
        text="[image generated: a sofa]",
        media=(MediaAttachment(ref=photo),),
    )
    result = ToolResult(call_id="c1", content=(ContentPart(kind="text", text="ok"),))
    from tiny_harness.harness.models import ToolResultItem

    state = (
        AgentState(task_id="t-1")
        .append(ToolResultItem(result=result))
        .append(note)
        .append(MessageItem(role=MessageRole.USER, text="next"))
        .append(MessageItem(role=MessageRole.ASSISTANT, text="ok"))
    )
    llm = FakeLLM([scripted("The agent drew a sofa.")])
    new_state = await compact(state, llm, store, info())
    assert new_state.summary.endswith(f'[image {photo.id} "photo.png": not described]')


async def test_a_plugin_summary_is_checked_for_media_lines_too(tmp_path: Path) -> None:
    store, photo, _, _, _ = await stored(tmp_path)
    hooks = HookManager()

    async def plugin(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, CompactionSummariseIn)
        assert [a.ref for a in ctx.media] == [photo]
        return ctx.model_copy(update={"result": "plugin summary"})

    hooks.register(FunctionExecutor("plugin", plugin, priority=10, points=[SUMMARISE]))
    llm = FakeLLM([])
    state = await compact(history(MediaAttachment(ref=photo)), llm, store, info(), hooks=hooks)
    assert llm.requests == []
    assert state.summary == f'plugin summary\n[image {photo.id} "photo.png": not described]'


async def test_without_a_media_store_media_is_named_from_its_reference() -> None:
    ref = MediaRef(
        id="m1", task_id="t-1", kind=MediaKind.IMAGE, media_type="image/png", size=1, name="a.png"
    )
    llm = FakeLLM([scripted("sum")])
    state = await compact(history(MediaAttachment(ref=ref)), llm, None, info())
    assert summarise_request(llm).media == ()
    assert state.summary == 'sum\n[image m1 "a.png": not described]'
