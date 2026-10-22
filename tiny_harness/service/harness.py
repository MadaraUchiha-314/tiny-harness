"""``Harness``: one agent's runtime, started from a host app's lifespan (issue-36 R1, R4, R5).

A ``Harness`` connects Temporal, builds the runtime and starts the worker; it serves
nothing. ``asgi_app()`` is the app the host mounts, available from construction and
answering ``503`` until the harness has started. Several harnesses run in one process, each
from its own ``Settings``: the process's ``Claims`` refuse a clash of agent id, task queue or
store file, the ``TemporalPool`` shares connections, and the process's secret registry makes
every agent's redactor mask every agent's secrets.

Starlette::

    support = Harness(Settings.load(Path("support.toml")), prefix="/agents/support")
    app = Starlette(
        routes=[Mount("/agents/support", app=support.asgi_app())],
        lifespan=harnesses_lifespan(support),
    )
"""

from __future__ import annotations

import contextlib
import logging
import weakref
from collections.abc import AsyncGenerator, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from functools import partial
from pathlib import Path
from types import TracebackType
from typing import Literal, Self, TextIO
from urllib.parse import urlsplit

import httpx
from a2a.server.tasks import BasePushNotificationSender
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.routing import BaseRoute
from temporalio.client import Client

from tiny_harness.config import Settings
from tiny_harness.errors import (
    HarnessAlreadyStartedError,
    HarnessNotStartedError,
    HarnessStoppedError,
)
from tiny_harness.harness.agents import SUPPORTED_EXTENSIONS
from tiny_harness.harness.commands import CommandHandler, CommandSpec
from tiny_harness.harness.media import MediaStore
from tiny_harness.harness.media.extension import MEDIA_EXT_URI
from tiny_harness.harness.models import (
    LLM,
    ImageGenerator,
    ModelCatalog,
    SpeechToText,
    TextToSpeech,
)
from tiny_harness.harness.plugins import Plugin
from tiny_harness.harness.security import PROCESS_SECRETS
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a import (
    HarnessExecutor,
    HarnessRequestHandler,
    PollingEventBridge,
    PushReceiver,
    PushSink,
    StorePushConfigStore,
    TemporalTaskStore,
    build_agent_card,
)
from tiny_harness.service.a2a.app import (
    ALL_ROUTES,
    DeferredRequestHandler,
    HarnessApp,
    ParticipantResolver,
    RouteGroups,
    RouteOptions,
    build_route_groups,
    wrap_middleware,
)
from tiny_harness.service.a2a.card import (
    AgentDescription,
    describe,
    normalize_prefix,
    public_url,
)
from tiny_harness.service.a2a.media_routes import MediaSource
from tiny_harness.service.claims import PROCESS_CLAIMS, Claim
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.temporal import temporal_client
from tiny_harness.service.durable.worker import build_worker, ensure_search_attributes
from tiny_harness.service.heartbeat import ensure_heartbeat_schedule
from tiny_harness.service.runtime import (
    build_runtime,
    retention_map,
    secret_values,
    workflow_config,
)

log = logging.getLogger("tiny_harness.harness")

_LOCAL_HARNESSES: weakref.WeakSet[Harness] = weakref.WeakSet()
"""Every harness built in this process. A harness whose ``[[agents]]`` names another one's
public URL gets that agent's card unfetched, since neither is listening while the host app
starts (issue-36 R6.1). A set, not a map by URL: a later harness with the same URL must not
push a live one out (self-review 2, #2); ``Claims`` refuses two running with one URL."""

Lifespan = Callable[[object], AbstractAsyncContextManager[None]]


class Harness:
    """One agent: its runtime, worker and routes, started with ``async with harness``.

    ``client`` is a Temporal client of yours, used and never closed; without one the
    harness connects per ``[temporal]`` through the process's pool. ``prefix`` is where the
    host mounts the agent; it may instead be the path of ``[server] base_url``, and the two
    must agree. ``participant`` names each request's participant from the host's own
    authentication; with it the ``X-Participant-Id`` header is ignored. ``routes`` turns the
    harness's own middleware and routes off one by one. ``agent`` describes the agent for
    its card; ``[agent]``'s name and description apply over it. ``plugins``, ``commands``,
    ``builtin_commands``, ``llm`` and the media seams (``speech_to_text``,
    ``text_to_speech``, ``image_generator``, ``media_store``) go to the runtime. A harness
    runs once."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Client | None = None,
        with_worker: bool = True,
        prefix: str | None = None,
        participant: ParticipantResolver | None = None,
        routes: RouteOptions = ALL_ROUTES,
        agent: AgentDescription | None = None,
        plugins: Sequence[Plugin | Path] = (),
        commands: Iterable[tuple[CommandSpec, CommandHandler]] = (),
        builtin_commands: bool = True,
        llm: LLM | None = None,
        log_stream: TextIO | None = None,
        speech_to_text: SpeechToText | None = None,
        text_to_speech: TextToSpeech | None = None,
        image_generator: ImageGenerator | None = None,
        media_store: MediaStore | None = None,
    ) -> None:
        if settings.temporal.mode == "embedded" and not with_worker and client is None:
            log.info("embedded mode: the worker runs in this process")
            with_worker = True
        self.settings = settings
        self._given_client = client
        self._with_worker = with_worker
        self._public_url = public_url(str(settings.server.base_url), prefix)  # R2.4, no I/O
        self._prefix = normalize_prefix(_path_of(self._public_url))
        self._participant = participant
        self._routes = routes
        self._agent = agent
        self._plugins = tuple(plugins)
        self._commands = tuple(commands)
        self._builtin_commands = builtin_commands
        self._llm = llm
        self._media_seams: dict[str, object] = {
            name: value
            for name, value in (
                ("speech_to_text", speech_to_text),
                ("text_to_speech", text_to_speech),
                ("image_generator", image_generator),
                ("media_store", media_store),
            )
            if value is not None
        }
        self._log_stream = log_stream
        self._state: Literal["new", "running", "stopped"] = "new"
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._card: AgentCard | None = None
        self._push: PushReceiver | None = None
        self._media: MediaSource | None = None  # the media route's source, once started
        self._activities: Activities | None = None
        self._handler = DeferredRequestHandler()
        self._groups: RouteGroups | None = None
        self._app: HarnessApp | None = None
        _LOCAL_HARNESSES.add(self)

    # --- identity ------------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return self.settings.agent.id

    @property
    def prefix(self) -> str:
        """Where the agent is mounted: ``/a/b``, or ``""`` at the root."""
        return self._prefix

    @property
    def public_url(self) -> str:
        """Where clients reach the agent, with no trailing slash; the card's URL."""
        return self._public_url

    @property
    def description(self) -> AgentDescription:
        """What the card says: ``agent`` when given in code, else ``[card]`` (issue-34)."""
        return self._agent or describe(self.settings.card)

    def unstarted_card(self) -> AgentCard:
        """The card as other agents of this process see it before this one has started:
        built from the settings, without the registered commands."""
        return build_agent_card(self.description, self._public_url)

    @property
    def started(self) -> bool:
        return self._state == "running"

    @property
    def client(self) -> Client:
        if self._client is None:
            raise HarnessNotStartedError("the harness is not started", agent=self.agent_id)
        return self._client

    @property
    def card(self) -> AgentCard:
        if self._card is None:
            raise HarnessNotStartedError("the harness is not started", agent=self.agent_id)
        return self._card

    @property
    def route_options(self) -> RouteOptions:
        return self._routes

    # --- routes --------------------------------------------------------------------------

    def route_groups(self) -> RouteGroups:
        """The agent's routes by kind, before any prefix; built once."""
        if self._groups is None:
            self._groups = build_route_groups(
                self._handler,
                lambda: self.card,
                config=self.settings.server,
                options=self._routes,
                monitor=self._monitor,
                push=lambda: self._push,
                participant=self._participant,
                media=(lambda: self._media) if self._serves_media else None,
            )
        return self._groups

    @property
    def _serves_media(self) -> bool:
        """Whether the agent has media to serve: ``[media]``, or a media store given."""
        return self.settings.media is not None or "media_store" in self._media_seams

    def routes(self) -> list[BaseRoute]:
        """The agent's routes, before any prefix. They need the harness started; mount
        ``asgi_app()`` to get the 503 gate and the mount check with them."""
        return self.route_groups().flat()

    def asgi_app(self) -> HarnessApp:
        """The app to mount at ``prefix``; the same object on every call (R2.1, R2.2)."""
        if self._app is None:
            inner = wrap_middleware(
                Starlette(routes=self.routes()),
                config=self.settings.server,
                options=self._routes,
                media=self.settings.media,
            )
            self._app = HarnessApp(
                agent_id=self.agent_id,
                prefix=self._prefix,
                inner=inner,
                started=lambda: self.started,
                lifespan=lambda: self,
            )
        return self._app

    async def _monitor(self) -> JsonObject:
        snapshot = self._activities.last_snapshot if self._activities is not None else None
        return snapshot.model_dump(mode="json") if snapshot is not None else {"tasks": []}

    # --- lifecycle -----------------------------------------------------------------------

    def lifespan(self, app: object) -> AbstractAsyncContextManager[None]:
        """A Starlette or FastAPI ``lifespan`` that runs this harness."""
        return harnesses_lifespan(self)(app)

    async def __aenter__(self) -> Self:
        if self._state == "running":
            raise HarnessAlreadyStartedError("the harness is running", agent=self.agent_id)
        if self._state == "stopped":
            raise HarnessStoppedError(
                "the harness has stopped; build a new one", agent=self.agent_id
            )
        stack = AsyncExitStack()
        try:
            await self._start(stack)
        except BaseException:
            self._state = "stopped"
            await stack.aclose()
            raise
        self._stack = stack
        self._state = "running"
        log.info("agent %s started at %s", self.agent_id, self._public_url or "/")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        stack, self._stack = self._stack, None
        self._state = "stopped"
        if stack is not None:
            await stack.aclose()
        log.info("agent %s stopped", self.agent_id)

    async def _start(self, stack: AsyncExitStack) -> None:
        """Each step is undone by the stack, in reverse, if a later one fails."""
        settings = self.settings
        queue = settings.temporal.effective_task_queue
        claim = Claim(
            agent_id=self.agent_id,
            # The namespace the queue is actually polled in: a client of the caller's own
            # may serve another than the settings name.
            namespace=(
                self._given_client.namespace
                if self._given_client is not None
                else settings.temporal.effective_namespace
            ),
            task_queue=queue,
            store_path=settings.store.sqlite_path,
            public_url=self._public_url,
        )
        PROCESS_CLAIMS.claim(claim)  # R5.3, R5.8: before anything connects
        stack.callback(PROCESS_CLAIMS.release, claim)
        secrets = secret_values(settings)
        PROCESS_SECRETS.register(secrets)  # abuse case 6
        stack.callback(PROCESS_SECRETS.unregister, secrets)
        if self._given_client is not None:
            client = self._given_client  # R1.3: the caller's, never closed here
        else:
            client = await stack.enter_async_context(
                temporal_client(settings, output=self._log_stream)
            )
        # ``llm`` and the media seams only when given: a caller (or a test) may have bound
        # them into the builder.
        seams = dict(self._media_seams)
        if self._llm is not None:
            seams["llm"] = self._llm
        build = partial(build_runtime, **seams) if seams else build_runtime
        runtime = await build(
            settings,
            plugins=self._plugins,
            commands=self._commands,
            builtin_commands=self._builtin_commands,
            public_url=self._public_url,
            description=self.description,
            local_cards={
                peer.public_url: peer.unstarted_card()
                for peer in list(_LOCAL_HARNESSES)
                if peer is not self and peer._state != "stopped"
            },
        )
        push_store = StorePushConfigStore(runtime.store)
        push_http = httpx.AsyncClient(timeout=10)
        stack.push_async_callback(push_http.aclose)
        bridge = PollingEventBridge(client, interval=settings.server.bridge_interval)
        runtime.commands.freeze()  # no command is registered once the card is built
        await runtime.commands.publish(runtime.registry)
        card = build_agent_card(
            self.description,
            self._public_url,
            commands=runtime.commands.specs,
            media=runtime.media,
        )
        executor = HarnessExecutor(
            client,
            task_queue=queue,
            bridge=bridge,
            config=workflow_config(settings),
            redactor=runtime.redactor,
            delegators=settings.server.delegators,
            models=ModelCatalog.from_settings(settings).selectable,
            media_intake=runtime.media_intake,
            # a request may activate the media extension where the card declares it
            extensions=(
                (*SUPPORTED_EXTENSIONS, MEDIA_EXT_URI)
                if runtime.media.enabled
                else SUPPORTED_EXTENSIONS
            ),
        )
        activities = Activities(
            runtime.engine,
            commands=runtime.commands,
            sink=PushSink(push_store, push_http),
            client=client,
            retention=retention_map(settings),
            media_retention=settings.retention.media,
            # R4.5: without the push route, remote sub-tasks are followed instead
            push_base_url=self._public_url if self._routes.push else None,
            task_queue=queue,
        )
        task_store = TemporalTaskStore(client, runtime.store, task_queue=queue)
        handler = HarnessRequestHandler(
            bridge=bridge,
            agent_executor=executor,
            task_store=task_store,
            agent_card=card,
            push_config_store=push_store,
            push_sender=BasePushNotificationSender(push_http, push_store),
        )
        if self._with_worker:
            await ensure_search_attributes(client)
            await ensure_heartbeat_schedule(
                client,
                interval=settings.heartbeat.interval,
                task_queue=queue,
                agent_id=self.agent_id,
            )
            await stack.enter_async_context(
                build_worker(client, activities, task_queue=queue, agent_id=self.agent_id)
            )
        self._client = client
        self._card = card
        self._activities = activities
        self._push = PushReceiver(client, task_queue=queue)
        if runtime.media_store is not None:
            self._media = MediaSource(store=runtime.media_store, lookup=task_store.lookup)
        self._handler.target = handler
        stack.callback(self._forget)

    def _forget(self) -> None:
        self._handler.target = None
        self._push = None
        self._media = None
        self._client = None


def harnesses_lifespan(*harnesses: Harness) -> Lifespan:
    """One ``lifespan`` that starts ``harnesses`` in order and stops them in reverse."""

    @asynccontextmanager
    async def lifespan(app: object) -> AsyncGenerator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for harness in harnesses:
                await stack.enter_async_context(harness)
            yield

    return lifespan


def _path_of(url: str) -> str:
    return urlsplit(url).path


__all__ = ["Harness", "Lifespan", "harnesses_lifespan"]
