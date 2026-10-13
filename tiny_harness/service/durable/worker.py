"""The worker (R19.9, R19.11): registers the workflows and the activity set, and the
three search attributes the server lists tasks by (design.md § Data models)."""

from __future__ import annotations

import contextlib

from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest
from temporalio.client import Client
from temporalio.common import SearchAttributeKey
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
    Replayer,
    Worker,
)
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.workflows import (
    HeartbeatWorkflow,
    RemoteTaskWorkflow,
    TaskWorkflow,
)
from tiny_harness.service.o11y.logging import CURRENT_AGENT

A2A_CONTEXT_ID = SearchAttributeKey.for_keyword("A2AContextId")
A2A_TASK_STATE = SearchAttributeKey.for_keyword("A2ATaskState")
TINY_HARNESS_AGENT = SearchAttributeKey.for_keyword("TinyHarnessAgent")
SEARCH_ATTRIBUTES = (A2A_CONTEXT_ID, A2A_TASK_STATE, TINY_HARNESS_AGENT)
WORKFLOWS = (TaskWorkflow, RemoteTaskWorkflow, HeartbeatWorkflow)

# Modules passed through the workflow sandbox (R19.9): the harness's own pure models and
# loop, the libraries they import at module level, and nothing that workflow code calls
# for time, randomness or I/O. Passing a module through shares the loaded module with
# the sandbox instead of re-importing it; the sandbox's call restrictions still apply.
PASSTHROUGH_MODULES = (
    "tiny_harness",  # harness.core models and the loop; service.durable.models
    "pydantic",  # Temporal's Pydantic integration requires it
    "pydantic_core",
    "a2a",  # the SDK's protobuf types
    "google.protobuf",
    "jsonschema",  # SchemaValidated state subsets
    "packaging",  # PEP 440 resolution in the registry models
    "httpx",  # imported at module level by hooks.providers (never called in a workflow)
    "starlette",  # pulled by a2a.utils at import
    "anyio",
    "sniffio",
    "mcp",  # imported at module level by tools.mcp (never called in a workflow)
    "yaml",  # skills and prompts front matter
    "opentelemetry",  # Temporal's TracingInterceptor propagates context inside workflows
)


def workflow_runner() -> SandboxedWorkflowRunner:
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(*PASSTHROUGH_MODULES)
    )


async def ensure_search_attributes(client: Client) -> None:
    """Register the keyword search attributes; already-registered ones are fine."""
    with contextlib.suppress(Exception):
        await client.operator_service.add_search_attributes(
            AddSearchAttributesRequest(
                namespace=client.namespace,
                search_attributes={
                    key.name: IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD
                    for key in SEARCH_ATTRIBUTES
                },
            )
        )


def build_replayer() -> Replayer:
    """A replayer with the same sandbox configuration as the worker (R19.2 evidence)."""
    return Replayer(workflows=list(WORKFLOWS), workflow_runner=workflow_runner())


class AgentContextInterceptor(Interceptor):
    """Sets ``CURRENT_AGENT`` for every activity this worker runs (issue-36 NFR
    observability): the activity's log lines and spans name their agent."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _AgentActivityInbound(next, self.agent_id)


class _AgentActivityInbound(ActivityInboundInterceptor):
    def __init__(self, next: ActivityInboundInterceptor, agent_id: str) -> None:
        super().__init__(next)
        self._agent_id = agent_id

    async def execute_activity(self, input: ExecuteActivityInput) -> object:
        token = CURRENT_AGENT.set(self._agent_id)
        try:
            return await super().execute_activity(input)
        finally:
            CURRENT_AGENT.reset(token)


def build_worker(
    client: Client,
    activities: Activities,
    *,
    task_queue: str,
    tracing: bool = True,
    max_cached_workflows: int = 1000,
    agent_id: str | None = None,
) -> Worker:
    """The worker; ``tracing`` adds Temporal's OpenTelemetry interceptor (R17.4).

    A client interceptor that is also a worker interceptor is prepended to every worker
    on that client, so a client built by ``connect()`` already traces activities: adding
    a second one would emit every Start/Run activity span twice.
    """
    traced = any(isinstance(i, TracingInterceptor) for i in client.config()["interceptors"])
    interceptors: list[Interceptor] = [TracingInterceptor()] if tracing and not traced else []
    if agent_id is not None:
        interceptors.append(AgentContextInterceptor(agent_id))
    return Worker(
        client,
        task_queue=task_queue,
        workflows=list(WORKFLOWS),
        activities=list(activities.all()),
        workflow_runner=workflow_runner(),
        interceptors=interceptors,
        # 0 turns sticky execution off, so another worker answers a query at once.
        max_cached_workflows=max_cached_workflows,
    )


__all__ = [
    "A2A_CONTEXT_ID",
    "A2A_TASK_STATE",
    "PASSTHROUGH_MODULES",
    "SEARCH_ATTRIBUTES",
    "TINY_HARNESS_AGENT",
    "WORKFLOWS",
    "AgentContextInterceptor",
    "build_replayer",
    "build_worker",
    "ensure_search_attributes",
    "workflow_runner",
]
