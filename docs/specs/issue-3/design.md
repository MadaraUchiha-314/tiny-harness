---
type: design
phase: design
workItem: issue-3
status: approved
approvedBy: ["MadaraUchiha-314"]
overrides: {}
---

<!-- Written per the `the-loop:writing` skill: front-load each section's
     conclusion, draw it rather than describe it (3+ named parts -> a mermaid
     diagram), and keep the formal registers formal (EARS, abuse cases,
     RFC-2119, API contracts, schema descriptions). No length limit — length
     follows the change; the test is whether a sentence can come out without
     losing information. A gated section stays even when it is empty. -->

# Design: tiny-harness: A tiny agent harness

> Phase 2 of 3 (requirements → design → tasks). Derives from the approved
> requirements. MUST be reviewed and approved before moving to tasks breakdown.

## Overview

The harness is one Temporal workflow per task running sherma's five-line loop, where
everything the LLM can make the harness do is a tool call, every operation is an activity
wrapped in a hook chain, and every construct is a registry entity a plugin can replace.
The A2A server is a thin adapter: it turns a request into an update-with-start on the task
workflow and streams the workflow's events back. Two renderers, a Textual TUI and a React
web app, are plain A2A clients that also speak the A2UI extension.

Three decisions shape everything below:

- [decision-002](../../decisions/decision-002.md): Temporal owns the whole request
  lifecycle; the inbox is the workflow mailbox; the event bridge polls workflow queries.
- [decision-003](../../decisions/decision-003.md): no authentication in this release; a
  perimeter authenticates, and the A2A SDK's security schemes are the later hook.
- [decision-004](../../decisions/decision-004.md): plans, steps, help requests, sub-tasks
  and skills are tools, so the loop stays the ticket's pseudo-code.

Where the requirements name a version "current on 2026-10-09", this design pins:
`a2a-sdk` 1.2, `mcp` 2.3, `temporalio` 1.34, `openai` 3.27, `anthropic` 1.13,
`opentelemetry-sdk` 1.45, `textual` 8.2, React 19.3, and **A2UI 0.9.1** (the 1.0
candidate has no library support: the official renderers and SDKs cover 0.8–0.9.1 only, so the
approver's rule picks 0.9.1). Every signature quoted below was read from the installed
packages on Python 3.14.7, where all of them import. Exact pins land in `pyproject.toml`
and `renderers/web/package.json` at implementation; the testing plan verifies them.

## Architecture

### Layers and modules

The package mirrors the diagram: one top-level module per column, one sub-module per box
(Requirement 22.1).

```mermaid
flowchart LR
  subgraph interaction["tiny_harness.interaction"]
    tui["tui/ (Textual)"]
    a2ui["a2ui/ (extension + catalog)"]
    surface["surface.py · renderer.py"]
  end
  web["renderers/web (React, TS)"]
  subgraph service["tiny_harness.service"]
    a2a["a2a/ (server, card, extensions, bridge)"]
    inbox["inbox.py"]
    heartbeat["heartbeat.py"]
    chsvc["channels.py (A2A exposure)"]
    o11y["o11y/ (plugin)"]
    durable["durable/ (workflows, activities, worker)"]
  end
  subgraph harness["tiny_harness.harness"]
    entities["entities/ (base, registry)"]
    hooks["hooks/"]
    plugins["plugins/"]
    prompts["prompts/"]
    skills["skills/"]
    tools["tools/ (MCP, intrinsics)"]
    models["models/ (llm, systemone)"]
    core["core/ (task, plan, state, context, compaction, loop)"]
    persistence["persistence/"]
    channels["channels/"]
    agents["agents/ (local, remote A2A)"]
  end
  config["tiny_harness.config"]
  tui --> a2a
  web --> a2a
  a2a --> durable
  inbox --> durable
  heartbeat --> durable
  durable --> core
  core --> tools & models & prompts & skills & channels & persistence
  hooks -.wrap every activity.-> durable
  plugins --> entities
  o11y -.hooks.-> hooks
```

| Diagram box | Module | Requirement |
|---|---|---|
| Surface, Renderer, Web renderer, TUI renderer | `interaction/surface.py`, `interaction/renderer.py`, `renderers/web`, `interaction/tui` | R20 |
| Events, Inbox | `service/inbox.py` + the task workflow's mailbox | R15 |
| Heartbeat | `service/heartbeat.py` (Temporal schedule + workflow) | R16 |
| API Server (A2A) | `service/a2a/` | R14 |
| Channels (service) | `service/channels.py` (A2A extension) | R13 |
| o11y | `service/o11y/` (a plugin) | R17 |
| Durable Execution | `service/durable/` | R19 |
| Sys Prompt | `harness/prompts/` | R4 |
| Skills | `harness/skills/` | R5 |
| Tools, MCP | `harness/tools/` | R6 |
| Hooks | `harness/hooks/` | R2 |
| Models: LLM, SystemOne | `harness/models/` | R18 |
| Core Loop, Task, Plan, Step, State, Context Window Manager, Compaction | `harness/core/` | R8, R9, R10 |
| Persistence | `harness/persistence/` | R11 |
| A2A (client) | `harness/agents/remote.py` | R7 |
| Channels (harness) | `harness/channels/` | R12, R13 |
| (principles) entity, registry, plugin | `harness/entities/`, `harness/plugins/` | R1, R3 |
| (cross-cutting) configuration | `config.py` | R21 |
| Memory, Sandbox, Self-improvement | not built; `tools/` leaves a `ToolKind` slot | out of scope |

### A request's life

```mermaid
sequenceDiagram
  participant S as Surface (TUI / web)
  participant A as A2A server (service/a2a)
  participant T as Temporal
  participant W as TaskWorkflow (service/durable)
  participant X as Activities (worker)
  S->>A: SendStreamingMessage
  A->>T: update-with-start TaskWorkflow(task_id).inbox(message)
  T-->>A: update accepted (message in history)
  A->>T: query events_since(0) … (poll every 250 ms)
  T->>W: run / resume
  loop core loop
    W->>X: assemble_context (hooks pre/in/post)
    W->>X: invoke_llm (hooks)
    W->>W: tool calls? none → break
    W->>X: invoke_tool × n (hooks) or intrinsic in-workflow
    W->>X: emit_event (persist, push notification configs)
  end
  T-->>A: events (status, artifacts, messages)
  A-->>S: SSE stream
  W->>W: INPUT_REQUIRED → wait_condition(reply)
  S->>A: SendMessage (reply on channel)
  A->>T: update TaskWorkflow.inbox(reply)
  W->>W: resume
```

The dashed obligations of decision-002: the message is in Temporal history before the
server acknowledges; the executor never runs loop code; a crash of the worker leaves the
workflow to resume on another worker from history; a crash of the server leaves the
workflow running and a reconnecting surface calls `SubscribeToTask`, which attaches a
new poller that replays the task's durable event log from sequence 0, so an outage skips
nothing.

### The core loop

```mermaid
flowchart TD
  start([inbox message]) --> ctx["assemble_context (activity)"]
  ctx --> cmp0{over budget?<br/>compaction.trigger.in}
  cmp0 -- yes --> compact0["compact (activity: keep.in, summarise.in)"]
  compact0 --> ctx
  cmp0 -- no --> llm["invoke_llm (activity)"]
  llm --> tc{tool calls?}
  tc -- none --> done{"task.complete.in:<br/>sub-tasks resolved?"}
  done -- wait --> wait2["wait_condition(children resolved)"] --> done
  done -- complete --> fin["final status (activity: emit_event)"]
  tc -- any tool --> act["invoke_tool (activity: validate, hooks, body)"]
  act -- MCP result --> rec["append results to history"]
  act -- WorkflowCommand --> intr["apply command in workflow: attach plan / wait / spawn child / mark loaded skill"]
  intr --> rec
  rec --> ctx
  intr -. ask_participant .-> wait["INPUT_REQUIRED: wait_condition(reply)"]
  wait --> rec
```

## Components & interfaces

Every signature below is a public interface under Requirement 23: the design-approval
gate reviews it, a contract test pins it, and an incompatible change fails that test. All
models are Pydantic v2 (`BaseModel`, `frozen=True` where stated); `Any` appears nowhere.

### Entities and registry (R1) — `harness/entities/`

```python
class EntityKind(StrEnum):
    PROMPT = "prompt"; SKILL = "skill"; TOOL = "tool"; LLM = "llm"; SYSTEM_ONE = "system_one"
    HOOK = "hook"; CHANNEL = "channel"; RENDERER = "renderer"; STORE = "store"; AGENT = "agent"

class EntityRef(BaseModel, frozen=True):
    """Registry reference. `version` is None for kinds that are not versioned."""
    kind: EntityKind
    id: str
    version: str | None = None          # PEP 440 specifier; "*" = latest concrete

class TransportProtocol(StrEnum):
    A2A = "a2a"; MCP = "mcp"; HTTPS = "https"

class Entity(ABC):
    ref: EntityRef
    @property
    @abstractmethod
    def kind(self) -> EntityKind: ...

class RegistryEntry[T: Entity](BaseModel):
    ref: EntityRef
    instance: T | None = None
    factory: Callable[[], T | Awaitable[T]] | None = None
    remote: RemoteLocation | None = None    # url + protocol; exactly one of instance/factory/remote

class RemoteLocation(BaseModel, frozen=True):
    url: HttpUrl
    protocol: TransportProtocol

class Registry:
    async def add(self, entry: RegistryEntry[Entity], *, override: bool = False) -> None
    async def get[T: Entity](self, ref: EntityRef, kind: type[T]) -> T      # EntityNotFoundError
    async def remove(self, ref: EntityRef) -> None
    def list(self, kind: EntityKind | None = None) -> Sequence[EntityRef]
```

Divergences from sherma, each deliberate: `version` is `str | None` instead of a required
string defaulting to `"*"` (Requirement 1.2); `tenant_id` is dropped (multi-tenancy is out
of scope; a later work item adds it on the ref); `RemoteLocation` is a required pair, so a
remote entry cannot lack a protocol (1.5); kind-specific `fetch` is a method of the
protocol adapter (`agents/remote.py`, `tools/mcp.py`), not of a per-kind registry
subclass, so there is one registry with typed `get`. Version resolution reuses sherma's
algorithm (`packaging.SpecifierSet`; `packaging` is already a transitive dependency of
`openai`).

### Hooks (R2) — `harness/hooks/`

```python
class Operation(StrEnum):
    REQUEST_RECEIVED = "request.received"; TASK_CREATED = "task.created"
    TASK_STATE_CHANGED = "task.state_changed"; CONTEXT_CREATED = "context.created"
    LLM_INVOKED = "llm.invoked"; TOOL_CALLS_EXTRACTED = "tool_calls.extracted"
    TOOL_INVOKED = "tool.invoked"; SYSTEM_ONE_INVOKED = "system_one.invoked"
    PLAN_CREATED = "plan.created"; STEP_STARTED = "step.started"; STEP_FINISHED = "step.finished"
    SUBTASK_SPAWNED = "subtask.spawned"; HELP_REQUESTED = "help.requested"; HELP_DECIDED = "help.decided"
    CHANNEL_SENT = "channel.sent"; CHANNEL_RECEIVED = "channel.received"
    COMPACTION = "compaction"; PERSISTENCE_READ = "persistence.read"; PERSISTENCE_WRITE = "persistence.write"
    ACTIVITY_FAILED = "activity.failed"; ACTIVITY_RETRIED = "activity.retried"
    HEARTBEAT_TICK = "heartbeat.tick"; SHUTDOWN = "shutdown"
    SKILL_LOADED = "skill.loaded"; SKILL_UNLOADED = "skill.unloaded"; AGENT_INVOKED = "agent.invoked"

class Phase(StrEnum):
    PRE = "pre"; IN = "in"; POST = "post"

class HookPoint(BaseModel, frozen=True):
    operation: Operation
    phase: Phase

class HookContext(BaseModel):
    """Base of every typed context: serialisable, carries refs not live objects."""
    task_id: str
    correlation_id: str
    participants: tuple[Participant, ...]
    entity: EntityRef | None            # the entity the operation acts on
    attempt: int = 1

# One Pre/Post context pair per operation (Post = Pre fields + the result), and an In
# context for every replaceable body. The full catalogue, which the contract test pins:
class RequestReceivedPre(HookContext):   message: Message
class TaskCreatedPre(HookContext):       task: HarnessTask
class TaskStateChangedPre(HookContext):  task_id: str; before: TaskState; after: TaskState
class ContextCreatedPre(HookContext):    state: AgentState
class ContextCreatedPost(ContextCreatedPre): window: ContextWindow
class LLMInvokedPre(HookContext):        request: LLMRequest
class LLMInvokedPost(LLMInvokedPre):     response: LLMResponse
class ToolCallsExtractedPre(HookContext): response: LLMResponse; calls: tuple[ToolCall, ...]
class ToolInvokedPre(HookContext):       call: ToolCall           # one call; veto by raising HookAbort
class ToolInvokedPost(ToolInvokedPre):   result: ToolResult
class SystemOneInvokedPre(HookContext):  state: str; questions: Mapping[str, Question]
class SystemOneInvokedPost(SystemOneInvokedPre): answers: Mapping[str, Answer]
class PlanCreatedIn(HookContext):        task: HarnessTask; result: Plan | None = None
class StepStartedPre(HookContext):       step: Step
class StepFinishedPre(HookContext):      step: Step; output: str | None
class SubtaskSpawnedPre(HookContext):    parent: TaskRef; child: TaskRef
class HelpRequestedPre(HookContext):     need: HelpNeed
class HelpDecidedIn(HookContext):        need: HelpNeed; result: HelpDecision | None = None
class ChannelSentPre(HookContext):       message: ChannelMessage
class ChannelReceivedPre(HookContext):   message: ChannelMessage
class CompactionTriggerIn(HookContext):  window: ContextWindow; model: LLMModelInfo; result: bool | None = None
class CompactionKeepIn(HookContext):     window: ContextWindow; result: frozenset[str] | None = None   # section names
class CompactionSummariseIn(HookContext): window: ContextWindow; keep: frozenset[str]; result: ContextWindow | None = None
class PersistenceReadPre(HookContext):   kind: str; id: str
class PersistenceWriteIn(HookContext):   record: Record; result: Literal["stored"] | None = None   # replaceable target (R9.4)
class ActivityFailedPre(HookContext):    activity: str; error: ErrorInfo; policy: RetryPolicySpec
class ActivityRetriedPre(HookContext):   activity: str; policy: RetryPolicySpec; next_delay: timedelta   # rewrite policy/delay
class HeartbeatTickPre(HookContext):     snapshot: MonitorSnapshot
class ShutdownPre(HookContext):          reason: str
class SkillLoadedPre(HookContext):       skill: EntityRef
class SkillUnloadedPre(HookContext):     skill: EntityRef
class AgentInvokedPre(HookContext):      agent: EntityRef; message: Message
class TaskCompleteIn(HookContext):       task: HarnessTask; unresolved: tuple[TaskRef, ...]; result: CompletionDecision | None = None

class HookAbort(Exception):
    """Raised by an executor to cancel the operation; carries a typed reason."""
    reason: AbortReason

class HookExecutor(Protocol):
    name: str
    priority: int                                    # lower runs first; built-in defaults are 1000
    points: frozenset[HookPoint]
    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None: ...

class HookManager:
    def register(self, executor: HookExecutor) -> None
    async def run[C: HookContext](self, point: HookPoint, ctx: C) -> C
```

- **Semantics.** `run` passes the context through executors in `(priority, registration
  order)`; a returned context replaces the input for the next executor; `None` passes
  through (sherma's `HookManager`). `pre` replaces the operation's input, `post` its
  output, `in` its body: the built-in plugin registers the default body at priority 1000,
  so any executor with a lower priority that sets `result` wins (Requirement 2.2–2.3,
  decision-004's overridability).
- **Where hooks run.** Never in workflow code. Every operation is an activity, and the
  hook chain runs inside the activity around its body. Workflow-level transitions
  (`task.state_changed`, `step.started`, `subtask.spawned`) are dispatched through one
  `dispatch_hooks` activity. This satisfies 2.11 without sandbox pass-throughs for hook
  modules.
- **Remote executors.** `JsonRpcHookExecutor(url)` and `McpHookExecutor(server)` port
  sherma's two transports; the context is sent as JSON (Pydantic `model_dump_json`) and
  the reply parsed back into the same model. A transport error raises inside the
  activity, which fails the operation through the normal retry policy and runs
  `activity.failed`; nothing passes through silently (Requirement 2.6, reversing sherma).
- **Infrastructure providers (2.7)** are not serialisable hooks but a `Providers`
  object given to the harness at construction: `http_client_factory`, `clock`, `random`.
  Activities read them from the worker's dependency container; workflows use
  `workflow.now()` and `workflow.random()`.
- **Single tool-call veto (2.9).** `ToolInvokedPre` carries one `ToolCall`; the loop runs
  the chain once per call, so an executor can rewrite or abort that call alone.

### Plugins (R3) — `harness/plugins/`

```text
my-plugin/
  plugin.json                       # Agent Plugins 1.0.0 manifest
  skills/<name>/SKILL.md            # Agent Skills
  mcp.json                          # MCP servers
  io.github.madarauchiha-314.tiny-harness/     # the client namespace this harness reads
    hooks.json                      # [{name, priority, import_path | url | mcp: {...}, points?}]
    prompts/*.md                    # prompt entities, id = file stem
    systemprompt.md                 # optional replacement of the default system prompt
```

```python
class PluginManifest(BaseModel, extra="allow"):      # unknown top-level keys are non-fatal (spec)
    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$")]
    version: str; description: str | None = None; ...
class McpServerDef(BaseModel, extra="forbid"):        # discriminated on `type`
    type: Literal["stdio"]; command: str; args: list[str] = []; env: dict[str, str] = {}; cwd: str | None = None
class McpHttpServerDef(BaseModel, extra="forbid"):
    type: Literal["streamable-http"]; url: HttpUrl; headers: dict[str, str] = {}
class HookDef(BaseModel, extra="forbid"):
    name: str; priority: int = 500
    points: tuple[HookPoint, ...] | None = None          # None = every point the executor declares
    import_path: str | None = None                        # exactly one of import_path | url | mcp
    url: HttpUrl | None = None
    mcp: McpServerDef | McpHttpServerDef | None = None
class PromptDef(BaseModel, extra="forbid"): id: str; path: Path; extends: str | None = None
class Plugin(BaseModel):
    manifest: PluginManifest; root: Path | None
    skills: tuple[Path, ...]; mcp: Mapping[str, McpServerDef | McpHttpServerDef]
    hooks: tuple[HookDef, ...]; prompts: tuple[PromptDef, ...]; systemprompt: Path | None

class PluginLoader:
    async def load_directory(self, root: Path) -> LoadReport
    async def load(self, plugin: Plugin) -> LoadReport          # the programmatic form (3.2)
```

`LoadReport` lists each component as `loaded | skipped(reason)`; a manifest failure raises
`PluginError` before any component is touched (3.5). Path escape: every component path is
resolved and required to be inside `root` (3.6). Variable expansion is a pure function
`expand(value, {"PLUGIN_ROOT", "PLUGIN_DATA"})` applied to `args`, `env` values and `cwd`
only (3.7); a `command` containing `${` fails validation with `PluginError` and the
attempt is recorded, rather than being spawned literally (abuse case 3). The built-in plugin (`tiny_harness/builtin/`) is loaded first with the same
loader (3.9) and registers: the default system prompt, the intrinsic tools, the default
`in` bodies, the default channel, the SQLite store, the two renderers' catalogs.

### System prompt (R4) — `harness/prompts/`

`PromptEntity(ref, text: str, sections: tuple[PromptSection, ...])`. The default lives at
`tiny_harness/builtin/systemprompt.md` (4.4) and is parsed into named sections by its
`##` headings: `role`, `task`, `participants`, `tools`, `skills`, `rules`. A plugin
replaces the whole file (`systemprompt.md` in its namespace directory) or extends a
section (`prompts/<section>.md` with front matter `extends: participants`). The context
window manager renders the prompt first, from the stable sections only (4.3, 10.3).

### Skills (R5) — `harness/skills/`

```python
class SkillFrontMatter(BaseModel, extra="forbid"):
    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    license: str | None = None
    compatibility: Annotated[str, StringConstraints(max_length=500)] | None = None
    metadata: dict[str, str] = {}
    allowed_tools: tuple[str, ...] = ()           # `allowed-tools`, space separated
class Skill(Entity):
    front_matter: SkillFrontMatter; body: str; root: Path
    def resources(self) -> Sequence[SkillResource]  # scripts/, references/, assets/, one level deep
class SkillLoader:
    def load(self, directory: Path) -> Skill | SkillError
```

Disclosure (5.3) is three intrinsic tools: `list_skills` (names and descriptions, also
rendered into the prompt's `skills` section), `load_skill(name)` (body into the
never-compact set), `load_skill_resource(name, path)`. They are intrinsics, so they run in
the `invoke_tool` activity like every tool: the activity reads the skill directory,
connects the skill's `mcp.json` servers, registers their tools in the worker-local
registry, and returns a `skill_loaded` command carrying the skill body and the tool
definitions; the workflow records both in `AgentState.loaded_skills`, which
`assemble_context` reads on the next turn, so a different worker reproduces the same
context (5.6, 19.2). `unload_skill` reverses it with `skill_unloaded`.

### Tools and MCP (R6) — `harness/tools/`

```python
class Idempotency(StrEnum): IDEMPOTENT = "idempotent"; NOT_IDEMPOTENT = "not_idempotent"
class Execution(StrEnum): ACTIVITY = "activity"; INTRINSIC = "intrinsic"
class ToolDefinition(BaseModel, frozen=True):
    name: str; description: str; input_schema: JsonSchema; output_schema: JsonSchema | None
    idempotency: Idempotency = Idempotency.NOT_IDEMPOTENT
    execution: Execution = Execution.ACTIVITY
class ToolCall(BaseModel, frozen=True): call_id: str; name: str; arguments: JsonObject
class ToolResult(BaseModel, frozen=True): call_id: str; content: tuple[ContentPart, ...]; is_error: bool; untrusted: Literal[True] = True
class Tool(Entity):
    definition: ToolDefinition
    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand   # an intrinsic returns a command
class WorkflowCommand(BaseModel, frozen=True):      # applied by the workflow, deterministic, no I/O
    kind: Literal["attach_plan", "complete_step", "wait_for_reply", "spawn_subtask", "create_participant_task", "set_role", "skill_loaded", "skill_unloaded", "ui_emitted"]
    call_id: str; payload: JsonObject; result: ToolResult   # the result the LLM sees next turn
class McpToolSource:
    """One MCP server; lists tools and wraps each as a Tool."""
    def __init__(self, server: McpServerDef | McpHttpServerDef, client_factory: McpClientFactory)
    async def tools(self) -> Sequence[Tool]
```

`JsonSchema` and `JsonObject` are typed recursive aliases (`dict[str, JsonValue]`), not
`Any`. `McpToolSource` maps `mcp.Tool` (`name`, `description`, `input_schema`,
`output_schema`, `annotations`) into a `ToolDefinition`; `idempotency` is `IDEMPOTENT`
only when the server's `annotations.idempotent_hint` or `read_only_hint` is true, else
`NOT_IDEMPOTENT` (6.7). The MCP client is `mcp.Client(StdioServerParameters(command,
args, env, cwd))` or `mcp.Client(url)` for streamable HTTP; its outbound spans and
`traceparent` propagation are built in. Argument validation (6.4) uses `jsonschema`,
justified below. Tool
output is wrapped in `ToolResult.untrusted` and the context window manager renders it
inside a delimited `<tool_result name=…>` block with a fixed preamble that it is data
(6.5). Schema drift (abuse case 8): `McpToolSource` records each tool's schema hash at
registration; before the first invocation of any of a server's tools in a loop iteration,
`invoke_tool` re-lists that server's tools (one `list_tools` per server per iteration,
not per call) and compares hashes, whatever capabilities the server advertises. A
mismatch refuses the call with `ToolSchemaChangedError` until the tool is re-registered;
the error result tells the LLM the tool is unavailable.

### Agents, local and remote (R1.1, R7) — `harness/agents/`

```python
# The A2A SDK's own types are the harness's types; nothing mirrors them.
from a2a.types import AgentCard, Artifact, Message, Part, Task, TaskState, TaskStatusUpdateEvent, TaskArtifactUpdateEvent
A2AEvent = Message | Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent

class Agent(Entity):
    agent_card: AgentCard
    @abstractmethod
    def send_message(self, request: Message, *, extensions: Sequence[str] = ()) -> AsyncIterator[A2AEvent]: ...
    @abstractmethod
    async def cancel_task(self, task_id: str) -> Task: ...
class LocalAgent(Agent):      # the harness itself: send_message = update-with-start + event bridge
class RemoteAgent(Agent):     # a2a-sdk client; card fetched from /.well-known/agent-card.json

# harness/core/proto.py — the two helpers the SDK types need inside the harness:
type ProtoJson[M: google.protobuf.message.Message] = Annotated[M, _ProtoJsonSerializer]   # Pydantic field holding a proto, (de)serialised with MessageToDict / ParseDict
def participant_of(message: Message) -> str | None       # the asserted participant id from Message.metadata["participant_id"]
```

The SDK's protobuf classes ship `.pyi` stubs, so they type-check under pyright strict
and satisfy 22.2 as typed boundary values; `Message`, `Task`, `AgentCard`, `Part` and
`TaskState` are used as-is throughout `harness/`, `service/` and the renderers' generated
types. In workflow and activity payloads (19.10) a proto travels either as a top-level
argument (Temporal's Pydantic data converter keeps the protobuf JSON converter in its
chain) or as a `ProtoJson[M]` field of a Pydantic model. Pydantic models exist only for
what A2A does not define: the task extension, plans, hook contexts, configuration.

`RemoteAgent` refuses a card whose `capabilities.extensions` contains `required: true`
for a URI outside `SUPPORTED_EXTENSIONS` (7.4) and sends `A2A-Extensions` only with
advertised URIs (7.5). Delegation is the intrinsic `spawn_subtask(agent, goal)`: its
`invoke_tool` activity validates the agent reference and returns a `spawn_subtask`
command; the workflow starts a child `RemoteTaskWorkflow`, which sends the message as an
activity and relays status updates into the parent's sub-task record (7.3).

### Core: task, plan, state (R8, R9) — `harness/core/`

```python
class Role(StrEnum): ASSIGNEE = "assignee"; REPORTER = "reporter"; WATCHER = "watcher"; ADMIN = "admin"
class Participant(BaseModel, frozen=True): id: str; kind: Literal["human", "agent"]; role: Role; display_name: str
class TaskRef(BaseModel, frozen=True): task_id: str; agent: EntityRef | None   # None = this harness
class TaskExtensionData(BaseModel, extra="forbid"):      # what A2A's Task lacks (8.1), kept in Task.metadata
    name: str; type: str | None; goal: str; description: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    participants: tuple[Participant, ...]
    parent_tasks: tuple[TaskRef, ...]; sub_tasks: tuple[TaskRef, ...]
    plan: Plan | None
TASK_EXT_KEY: Final = "io.github.madarauchiha-314.tiny-harness/task"
class HarnessTask:
    """A typed view over one a2a.types.Task. The proto is the entity; nothing is duplicated."""
    proto: Task                                            # a2a.types.Task: id, context_id, status, artifacts, history, metadata
    @property
    def id(self) -> str: ...                               # proto.id
    @property
    def state(self) -> TaskState: ...                      # proto.status.state, authoritative (8.2)
    @property
    def ext(self) -> TaskExtensionData: ...                # parsed from proto.metadata[TASK_EXT_KEY]
    def with_ext(self, ext: TaskExtensionData) -> HarnessTask   # writes it back into proto.metadata
class Step(BaseModel):
    id: str; name: str; description: str; depends_on: tuple[str, ...]
    output: str | None = None; linked_tasks: tuple[TaskRef, ...] = (); state: StepState
class Plan(BaseModel):
    steps: tuple[Step, ...]
    @model_validator(mode="after")
    def acyclic(self) -> Self: ...         # PlanCycleError (9.5)
```

The A2A task is the task entity, extended through its metadata (8.2, 8.3). A2A's
`Task` is a protobuf message and cannot be subclassed to add fields, so the attributes
A2A lacks live in `Task.metadata[TASK_EXT_KEY]` as `TaskExtensionData` and `HarnessTask`
exposes them through typed accessors; the extension is advertised in the agent card
(Requirement 14.3). The same object is also emitted as a data part of media type
`application/vnd.tiny-harness.task+json` on every status update whose payload changed,
so renderers need no second call (9.6). Workflow state holds the `Task` proto (as a
`ProtoJson` field of `TaskStart`), never a copy of its fields.

### Context window manager and compaction (R10) — `harness/core/context.py`

```python
class Stability(StrEnum): STATIC = "static"; PER_TASK = "per_task"; PER_TURN = "per_turn"
class ContextSection(BaseModel, frozen=True):
    name: str; stability: Stability; never_compact: bool; content: str
class ContextWindow(BaseModel, frozen=True):
    sections: tuple[ContextSection, ...]   # in render order
    tools: tuple[ToolDefinition, ...]
    estimated_tokens: int
class ContextWindowManager:
    order: tuple[str, ...] = ("system_prompt", "participants", "skills_index", "task", "plan", "state_summary", "history", "tool_results")
    async def assemble(self, state: AgentState) -> ContextWindow
    async def needs_compaction(self, window: ContextWindow, model: LLMModelInfo) -> bool   # compaction.trigger.in
    async def compact(self, window: ContextWindow) -> tuple[ContextWindow, CompactionRecord]  # keep.in, summarise.in
```

The loop assembles, measures and compacts **before** every LLM call, then re-assembles,
so a large first message, a drained mailbox or a freshly loaded skill never reaches the
model over budget (10.4). The three replaceable policies are three `in` hook points
(10.7): `compaction.trigger.in` (default: estimated tokens above
`compaction_fraction` of `min(model context window, turn_budget_tokens)`),
`compaction.keep.in` (default: the never-compact set below), `compaction.summarise.in`
(default: summarise the oldest `PER_TURN` history with the LLM into `state_summary`).
The never-compact set (10.5) is `system_prompt`, `participants`, `task` (goal and
acceptance criteria), `plan`, and every `skill:<name>` section of a loaded skill.

Order is by stability: `system_prompt`, `participants`, `skills_index` and the tool
definitions are `STATIC` for the task and form the cached prefix; `task` and `plan` are
`PER_TASK`; `history`, `state_summary` and `tool_results` are `PER_TURN`. For OpenAI the
adapter sends the static sections as `instructions`, the rest as `input`, with
`prompt_cache_key = task_id` and `store=False`; the static prefix of the demo prompt is
measured at implementation and must exceed the provider's 1,024-token minimum (10.3).
Token estimation uses the previous turn's `usage.input_tokens` plus a 4-characters-per-token
estimate for the delta; no tokenizer dependency. **Demo budget** (non-functional
requirement "Cost"): `turn_budget_tokens = 12,000` input per turn, of which the static
prefix (system prompt, participants, skills index, the demo's two MCP tools plus the
twelve intrinsics' definitions) targets 2,500–3,500 tokens, above the 1,024-token cache
minimum and below a third of the budget; history and tool results fill the rest and
compaction triggers at 75 % (9,000); output targets ≤ 1,000 tokens per turn
(`max_output_tokens=2,000` as the hard cap). The e2e evidence records every turn's
`input_tokens`, `cached_tokens` and `output_tokens`; the demo passes the budget when no
turn exceeds 12,000 input or 2,000 output and `cached_tokens ≥ 2,000` from the second
turn on. A compaction records
`CompactionRecord(removed_ids, summary, tokens_before, tokens_after)` on the task and in
the store (10.6).

### Persistence (R11) — `harness/persistence/`

```python
class Store(Entity):
    async def put(self, record: Record) -> None
    async def get[R: Record](self, kind: type[R], id: str) -> R | None
    async def query[R: Record](self, kind: type[R], where: Filter) -> Sequence[R]
Record = TaskRecord | PlanRecord | StateRecord | ChannelMessageRecord | InboxAuditRecord | CompactionRecord | PushConfigRecord
```

The default is `SqliteStore` on the standard library `sqlite3`, one table per record kind
with a JSON column and indexed id, context and timestamp columns, run through
`asyncio.to_thread`. Limits: single process writer, no replication; production deployments
plug a store entity. What the store holds, and when (11.1, 11.5): `TaskRecord` on every
state change and at the terminal state; `PlanRecord` whenever a plan is attached or a
step changes (9.4); `StateRecord` at the end of every loop iteration (the typed
`AgentState.data` subset and the summary, not the raw history, which Temporal holds);
`ChannelMessageRecord` before delivery (13.2); `InboxAuditRecord` at intake;
`CompactionRecord` per compaction; `PushConfigRecord` per push config. Every write goes
through the `persist` activity, whose `persistence.write.in` body is the replaceable
target (a plugin can route plans to its own system, 9.4). Temporal history remains the
replay source; the store is the read model that outlives the workflow. Secrets never
enter a `Record`: fields are typed and none is a credential, with one encrypted
exception, the push-config token (finding 1 below, 11.4).

### Participants and channels (R12, R13) — `harness/channels/`

```python
class Channel(Entity):
    id: str; task_id: str; members: frozenset[str]          # participant ids
    async def send(self, message: ChannelMessage) -> None
    def receive(self) -> AsyncIterator[ChannelMessage]      # pull-based media implement this
    pull: bool                                              # True → heartbeat polls it
class ChannelMessage(BaseModel, frozen=True): id: str; channel_id: str; sender: str; parts: tuple[ContentPart, ...]; at: datetime
class HelpNeed(BaseModel): question: str; options: tuple[str, ...]; blocking_work: bool | None
class HelpRoute(StrEnum): ASK = "ask"; CREATE_TASK = "create_task"
class HelpDecision(BaseModel, frozen=True): route: HelpRoute; participant_id: str; question: str | None; options: tuple[str, ...]; name: str | None; goal: str | None; acceptance_criteria: tuple[str, ...]; reason: str
```

The default channel medium is A2A itself (`A2AChannel`): a `send` emits an A2A `Message`
event on the task carrying the channel extension data part; a participant sends by calling
`SendMessage` on the task with the same part. The channel extension
(`…/tiny-harness/channel`) defines `ChannelMessageData(channel_id, sender, text, parts)`
and the membership rule (13.3). `help.decided.in` has one default body (12.4): an LLM call
with structured output against the `HelpDecision` schema (`route: ASK | CREATE_TASK`,
`participant_id`, `question`, `options`, `name`, `goal`, `acceptance_criteria`,
`reason`), given the `HelpNeed` and the task; a validator then rejects an `ASK` whose
need names work that an acceptance criterion assigns to another participant, and
re-runs the body once with the validation error in context. An executor replaces the
body by setting `result`; the validator always runs. `ASK` is the
intrinsic `ask_participant`: it emits the help message, sets `INPUT_REQUIRED`, and the
workflow `wait_condition`s on the reply update (12.2, 12.5, 12.6). Completion (8.5): when the LLM emits no tool call, the workflow runs `task.complete.in`
with the list of unresolved sub-tasks (local children and remote tasks not in a terminal
state, `INPUT_REQUIRED` and `AUTH_REQUIRED` included); the default `CompletionDecision`
is `wait` while any is unresolved (the workflow `wait_condition`s on child completion,
then re-evaluates), and `complete` otherwise; an executor can return `complete` or
`fail(reason)` instead. `CREATE_TASK` is the
intrinsic `create_task_for_participant`: a `create_participant_task` command, on which
the workflow starts a child task workflow assigned to that participant and links it as a
sub-task (12.3). Every intrinsic therefore passes `invoke_tool`'s validation and the
per-call `ToolInvokedPre` veto (2.9) before the workflow applies its command.

### A2A server (R14) — `service/a2a/`

```python
class HarnessExecutor(AgentExecutor):           # a2a-sdk
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None
def build_agent_card(agent: LocalAgent, config: ServerConfig) -> AgentCard     # from the entity (14.2)
SUPPORTED_EXTENSIONS: Final = (TASK_EXT_URI, CHANNEL_EXT_URI, A2UI_EXT_URI)
class EventBridge(Protocol):
    def events(self, task_id: str, cursor: int) -> AsyncIterator[tuple[int, A2AEvent]]
class PollingEventBridge(EventBridge): interval: timedelta = 250 ms   # queries TaskWorkflow.events_since
def create_app(config: ServerConfig) -> Starlette   # mounts JSON-RPC, REST and agent-card routes
```

`a2a-sdk` 1.2 facts the adapter is built on: types are protobuf messages (`a2a.types`,
package `a2a.v1`; `Part` is one message with a `text | raw | url | data` oneof, built with
`a2a.helpers.proto_helpers.new_data_part`); there is no application wrapper, so
`create_app` mounts `create_agent_card_routes(card)`, `create_jsonrpc_routes(handler,
rpc_url="/")` and `create_rest_routes(handler)` on a Starlette app; the handler is
`DefaultRequestHandler(agent_executor=HarnessExecutor, task_store=TemporalTaskStore,
agent_card=card, push_config_store=StorePushConfigStore, push_sender=
BasePushNotificationSender)`; every dispatcher method requires `A2A-Version: 1.0` (a
missing header is read as 0.3 and refused), and both renderers send it.

`execute`: the Starlette middleware has already enforced `max_request_bytes` and the
per-peer rate limit, and `convert.from_proto_message` has validated the parts; `execute`
then calls
`client.execute_update_with_start_workflow(TaskWorkflow.inbox, message,
start_workflow_operation=WithStartWorkflowOperation(TaskWorkflow.run, start, id=task_id,
task_queue=…, id_conflict_policy=USE_EXISTING))`, then stream from `EventBridge` until a
final event or client disconnect, mapping each to `TaskUpdater` calls (`submit`,
`start_work`, `update_status`, `add_artifact`, `requires_input`, `complete`, `failed`,
`cancel`) so the SDK's streaming contract holds (14.5, 14.7). `cancel`: signal
`TaskWorkflow.cancel` and emit `CANCELED` (14.6). `GetTask` and `ListTasks` are served by
`TemporalTaskStore(TaskStore)` (`save`, `get`, `delete` with a `ServerCallContext`):
`get` queries the workflow's `task()` (or the `Store` for terminal tasks), `list` uses
Temporal visibility with search attributes `A2AContextId` and `A2ATaskState`. Push
notification configs live in the `Store` behind `PushNotificationConfigStore` and are
delivered by the `emit_event` activity through `BasePushNotificationSender`. The
`A2A-Extensions` header is parsed by the SDK into `RequestContext.requested_extensions`;
`HarnessExecutor` rejects a request whose set contains a URI outside
`SUPPORTED_EXTENSIONS` with `UnsupportedOperationError` before intake (14.4). `SubscribeToTask` is served by `HarnessRequestHandler(DefaultRequestHandler)`, whose
`on_subscribe_to_task` override attaches a fresh `PollingEventBridge` at cursor 0 for the
task (the workflow's `events_since(0)` returns the whole durable log, carried across
continue-as-new) and streams until a final event or disconnect; a terminal task whose
workflow is closed is replayed from the store's `TaskRecord.events`, which the final
`persist` wrote. The SDK's in-process queue manager is not relied on for recovery. A
multi-process deployment replaces `PollingEventBridge` with an implementation of the
SDK's own `TaskEventStream` seam (`DefaultRequestHandler(event_stream=…)`); the default
stays in-process. Extension URIs are under
`https://madarauchiha-314.github.io/tiny-harness/a2a/ext/<name>/v1`, the docs site the
owner controls; their JSON schemas live beside the docs and are what the contract tests
validate (23.2). No security scheme is declared (decision-003); the later integration
point is a `ServerCallContextBuilder` subclass reading `request.scope["user"]` into
`ServerCallContext.user`, which the SDK already threads into every handler.

### Inbox and events (R15) — `service/inbox.py`

The inbox is the task workflow's mailbox plus an audit row. Transport limits (size,
rate) are a Starlette middleware in front of the routes, so an oversized request is
rejected before anything reaches Temporal (abuse case 7). Everything else about intake is
durable: when the workflow drains a message from its mailbox it first runs the `intake`
activity, which runs `request.received` hooks (an executor may rewrite or abort the
message) and writes the `InboxAuditRecord`; the message is already in history, so a
crash between acceptance and intake loses nothing (19.12). The four A2A event payloads are accepted on
`SendMessage` (15.1): a `Message` is the message itself; the other three travel inside a
`Message` as one data part of media type `application/vnd.tiny-harness.event+json`,
defined by the task extension, `EventEnvelope(kind: "task" | "status_update" |
"artifact_update", payload)` validated against the committed schema. A `task` payload
creates or updates the task extension data; `status_update` and `artifact_update` from a
remote agent are routed to the sub-task record that references that remote task. An
envelope whose `kind` or payload fails validation is rejected with the A2A invalid-params
error before update-with-start.
`returnImmediately: true` returns the `Task` as soon as the update is accepted (15.2).
Processing policy (15.3): the workflow's `inbox` update appends to a mailbox list; the loop
drains the mailbox at the top of each iteration (so a message to an executing task is
seen when the current step finishes) and `wait_condition` wakes an idle task at once;
the `inbox.policy` executor can mark a message `interrupt`, which cancels the in-flight
activity and re-enters the loop (15.4). Unprocessed items survive restarts because they
are workflow state (15.5).

### Heartbeat (R16) — `service/heartbeat.py`

A Temporal **schedule** (`tiny-harness-heartbeat`, interval from config, default 30 s)
starts `HeartbeatWorkflow`, which runs two activities: `poll_channels` (every channel with
`pull=True`, forwarding found messages as updates to their task workflows) and
`monitor_snapshot` (lists open task workflows through visibility, runs
`heartbeat.tick` hooks with the snapshot, exposes it on `GET /_monitor` of the server
for the API layer). A failed tick is one failed workflow run; the schedule fires the next
on time (16.4). The schedule rather than a process loop because it survives the server
process and is visible in Temporal (16.5).

### Observability (R17) — `service/o11y/`

A plugin whose single `HookExecutor` subscribes to every `pre` and `post` point: it opens
a span on `pre` (name `{gen_ai.operation.name} {model}` for LLM calls, `execute_tool
{name}` for tools, `invoke_agent {name}` for the task), closes it on `post` with usage
attributes, and writes one structured log record per operation with task id, correlation
id and phase at the same level in every environment (17.1–17.3). Trace context crosses
Temporal through `temporalio.contrib.opentelemetry.TracingInterceptor` and MCP through
the SDK's built-in OTel middleware (17.4). Exporter: OTLP; a Langfuse endpoint and key
pair are configuration (17.5). A `Redactor` runs over every attribute and log field
before export: regexes for bearer tokens, `sk-` and `tmprl`-style keys, `Authorization`
headers, plus any value equal to a configured secret (17.6, abuse case 6).

### Models (R18) — `harness/models/`

```python
class LLMRequest(BaseModel, frozen=True):
    instructions: str                                  # the static prefix
    input: tuple[InputItem, ...]                       # messages, tool results
    tools: tuple[ToolDefinition, ...]
    response_format: JsonSchema | None = None
    cache_key: str | None = None
class LLMResponse(BaseModel, frozen=True):
    output_text: str; tool_calls: tuple[ToolCall, ...]; usage: Usage; model: str; finish: FinishReason
class Usage(BaseModel, frozen=True): input_tokens: int; cached_tokens: int; output_tokens: int
class LLM(Entity):
    info: LLMModelInfo                                  # context window size, provider
    async def invoke(self, request: LLMRequest) -> LLMResponse
    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]
class OpenAILLM(LLM):    # responses.create(model="gpt-6.1-sol", instructions, input, tools, prompt_cache_key, store=False); AsyncOpenAI(max_retries=0); usage.input_tokens_details.cached_tokens
class AnthropicLLM(LLM): # Messages API, cache_control on the static prefix; configurable, not exercised e2e

class NoulQuestion(BaseModel, frozen=True):   kind: Literal["noul"]; instructions: str
class ChoiceQuestion(BaseModel, frozen=True): kind: Literal["choice"]; instructions: str; options: Mapping[str, str]
class ScoreQuestion(BaseModel, frozen=True):  kind: Literal["score"]; instructions: str; levels: tuple[str, ...]
Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="kind")]
class NoulAnswer(BaseModel, frozen=True):   kind: Literal["noul"]; probability: float
class ChoiceAnswer(BaseModel, frozen=True): kind: Literal["choice"]; choice: str; confidence: float; probabilities: Mapping[str, float]
class ScoreAnswer(BaseModel, frozen=True):  kind: Literal["score"]; score: float; confidence: float; probabilities: Mapping[int, float]
Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="kind")]
class SystemOne(Entity):
    async def decide(self, state: str, questions: Mapping[str, Question], *, timeout: timedelta) -> Mapping[str, Answer]
class FakeSystemOne(SystemOne): ...            # deterministic, for tests; the only implementation shipped
```

The System One interface mirrors `typesafe-sdk`'s shapes one to one (`Noul`, `Choice`,
`Score` questions; `NoulAnswer.noul`, `ChoiceAnswer.choice/confidence/probabilities`,
`ScoreAnswer.score/confidence/probabilities`; `AsyncTypeSafeClient.system_one(state,
questions)`), so the later Jev adapter is a field-for-field mapping with no interface
change (18.2). The loop does not call it in this work
item; `help.decided.in`'s default body is defined under Participants and channels.

### Durable execution (R19) — `service/durable/`

```python
@workflow.defn
class TaskWorkflow:
    @workflow.run
    async def run(self, start: TaskStart) -> TaskRecord
    @workflow.update
    async def inbox(self, message: Message) -> InboxReceipt      # the inbox (15)
    @workflow.signal
    async def cancel(self, reason: str) -> None
    @workflow.query
    def task(self) -> Task                                             # the a2a.types.Task, extension in metadata
    @workflow.query
    def events_since(self, cursor: int) -> EventPage                   # the event bridge reads this
@workflow.defn
class RemoteTaskWorkflow: ...     # one delegated remote task (7.3)
@workflow.defn
class HeartbeatWorkflow: ...

# activities (service/durable/activities.py), each a hook-wrapped body:
assemble_context, invoke_llm, invoke_tool, compact, persist, send_channel_message,
emit_event, dispatch_hooks, run_remote_agent_turn, poll_channels, monitor_snapshot, intake
```

- **Retry policy (19.3–19.5): attempts are managed by the workflow, not by Temporal's
  retry.** Every activity is scheduled with `RetryPolicy(maximum_attempts=1)`. On
  failure (an `ActivityError`, including the timeout a dead worker produces), the
  workflow runs the `dispatch_hooks` activity for `activity.failed.pre` and
  `activity.retried.pre` with the `RetryPolicySpec` for that activity (from
  `RetryPolicies`, per activity or default) and the computed next delay; the returned
  context may rewrite the policy or the delay, or abort. If attempts remain, the workflow
  `workflow.sleep`s the delay and schedules the activity again with `attempt + 1` in its
  input; otherwise the operation fails. Exponential backoff is
  `initial_interval × backoff_coefficient^(attempt − 1)`, capped at `maximum_interval`,
  jittered with `workflow.random()`. `invoke_tool` for a `NOT_IDEMPOTENT` tool has
  `maximum_attempts=1` in its spec, so a failure becomes a `ToolNotRetriedError` error
  `ToolResult` unless `activity.retried.pre` raises the attempts.
- **Failure detection (19.6).** Every activity has `start_to_close_timeout`; LLM and tool
  activities heartbeat every 10 s with `heartbeat_timeout=30 s`, so a killed worker
  surfaces as a timeout failure on the retry path above within 30 s and the next attempt
  runs on another worker.
- **Replay safety (19.2).** Activities return typed results recorded in history; the
  workflow never calls a model or a tool directly. Tool-call extraction is a pure function
  of the recorded `LLMResponse`. **The residual window:** an activity is at-least-once,
  so a worker that dies after the provider answered but before Temporal recorded the
  result re-runs the call on the next attempt. For `invoke_llm` that is one duplicated
  provider call (cost, no state change: `store=False`); for a `NOT_IDEMPOTENT` tool the
  retry path refuses, so the step fails with `ToolNotRetriedError` rather than
  duplicating a side effect. No external idempotency key closes the LLM window (the
  Responses API offers none), so the design states it rather than claiming otherwise.
  The demo (24.5) kills the worker at two points where the guarantee holds and is
  observable: during an idempotent fixture tool's activity, and during the
  `INPUT_REQUIRED` wait; the trace proves one LLM span and one tool span per step across
  the restart. The approver confirms this narrowing at design-approval (raised in Open
  questions).
- **Multi-turn (19.7).** The `inbox` update appends to the mailbox; the loop awaits
  `workflow.wait_condition(lambda: self.mailbox)` while `INPUT_REQUIRED`, consuming no
  worker slot.
- **History bound (19.8), the rollover contract.** After each loop iteration, if the
  workflow's current history length (`workflow.info().get_current_history_length()`)
  exceeds `history_event_bound` (default 10,000), the workflow awaits
  `workflow.all_handlers_finished()` (so no `inbox` update is mid-flight), then
  `continue_as_new(TaskStart(...))`. `TaskStart` is the complete state:

  ```python
  class TaskStart(BaseModel, frozen=True):
      task: ProtoJson[Task]; state: AgentState           # the A2A task proto; compacted history and loaded skills
      mailbox: tuple[Message, ...]                 # undrained messages, in order
      seen_message_ids: frozenset[str]                    # dedup across runs
      events: tuple[tuple[int, A2AEvent], ...]        # the tail of the durable event log
      next_event_seq: int                                 # monotonic across runs
      pending_help: HelpRequest | None                    # the open ask_participant, if waiting
      children: tuple[ChildRef, ...]                      # child workflow ids to re-attach by handle
      attempt_counters: Mapping[str, int]
  ```

  The first run starts from `TaskStart(task=..., state=empty, mailbox=(first message,),
  ...)`. The event bridge's cursor is `next_event_seq`-based, so a poller keeps working
  across the rollover; the first run's tail stays queryable until the new run has
  acknowledged it (the bridge reads the new run's `events_since`, which includes the
  carried tail). Child workflows are re-attached through
  `workflow.get_external_workflow_handle`, so their completions still reach the parent.
- **Sandbox (19.9).** Workflow modules import only `tiny_harness.harness.core` models and
  `pydantic`; `pydantic` is passed through (`workflow.unsafe.imports_passed_through`) as
  Temporal's Pydantic integration requires; nothing else. Payloads use
  `pydantic_data_converter` (19.10).
- **Connection (19.11).** `Client.connect(address, namespace=…, api_key=…, tls=True,
  data_converter=pydantic_data_converter, interceptors=[TracingInterceptor()])` from
  `TemporalConfig`; the worker and the server share one client. `temporalio`'s
  `openai-agents` and `google-adk` extras pin `mcp<2` and are never installed.
- **Lifecycle (19.12, decision-002).** middleware limits → `execute` → update-with-start
  → workflow drains the mailbox → `intake` activity → loop; bridge streams. Heartbeat is
  a schedule. Channel delivery and persistence are activities.

### Surfaces and renderers (R20) — `interaction/`, `renderers/web`

```python
class Modality(StrEnum): TEXT = "text"
class Surface(Entity): modality: Modality; renderer: EntityRef
class Renderer(Entity):
    supported: frozenset[str]                           # media types / part kinds it renders
    def render(self, event: A2AEvent) -> RenderPlan     # placeholder for unsupported kinds (20.4)
```

Both renderers are A2A clients of the server and nothing else (20.2), each through the
official SDK of its language: the TUI uses `a2a-sdk`'s client over JSON-RPC with
streaming; the web app uses `@a2a-js/sdk` 1.3's `ClientFactory` (protocol 1.0), which
resolves the agent card and picks the JSON-RPC transport the card advertises (the
approver's requirement of 2026-10-10: no hand-rolled client on any hop, web, TUI or
agent to agent). The web renderer's look is shadcn (Tailwind v4, the shadcn/ui
primitives and the June 2026 chat components `MessageScroller`, `Message`, `Bubble`,
`Marker`; the approver's second request of 2026-10-10: beautiful, minimal, elegant),
with the A2UI card still drawn by the official renderer inside an outline bubble. Each keeps a `SubscribeToTask` stream per open task, so two surfaces see the same
events (20.3); the SDK ends a stream at every final event, `INPUT_REQUIRED` included, so
the web renderer reopens its subscription after a pause while the task is not finished,
and the bridge's replay runs past an earlier final event to the newest one. Layout, states and interactions are the HTML prototypes in the UI/UX
inventory below. A2UI (20.5–20.6): **version 0.9.1**, extension URI
`https://a2ui.org/a2a-extension/a2ui/v0.9.1`, parts of media type
`application/a2ui+json`, card params `supportedCatalogIds` and `acceptsInlineCatalogs`.
The 1.0 candidate has no library support (the official renderers and SDKs implement the
0.9 family), which is the approver's stated condition for staying on 0.9. **Renderers use
the official A2UI renderer and the default catalog, nothing else:** the web renderer
takes `@a2ui/react` (0.10.x) with `@a2ui/web_core`, its `MessageProcessor` fed with the
`application/a2ui+json` parts and its `A2uiSurface` rendering the bundled `basicCatalog`;
user actions come back through the renderer's action callback and are sent as A2A
messages. No A2UI component is hand-written for the web. The TUI has no official
renderer, so `interaction/tui/a2ui.py` maps the basic catalog onto Textual widgets
(Video and AudioPlayer render the placeholder). **On the agent side no A2UI SDK is
used:** the Python `a2ui-agent-sdk` targets the 0.3.x A2A types and fails to import
against `a2a-sdk` 1.2 (and depends on `google-adk`), and A2A ≥ 1.0 is non-negotiable. The
harness emits A2UI payloads itself through the `emit_ui` intrinsic: `interaction/a2ui/`
holds typed models for the four server messages (`createSurface`, `updateComponents`,
`updateDataModel`, `deleteSurface`) and the two client messages (`action`, `error`),
validates every payload against the 0.9.1 `catalog.json`, `common_types.json` and
`server_to_client.json` vendored (Apache-2.0, with attribution) under
`interaction/a2ui/schemas/`, and discards an action whose surface or component id the
task did not create (abuse case 9). MCP Apps: `Renderer.
supported` can declare `text/html;profile=mcp-app` later; nothing else is built (20.7).

### Configuration (R21) — `config.py`

```python
class TemporalConfig(BaseModel, extra="forbid"):  address: str; namespace: str; api_key: SecretStr; task_queue: str = "tiny-harness"; tls: bool = True
class OpenAIConfig(BaseModel, extra="forbid"):    api_key: SecretStr; model: str = "gpt-6.1-sol"; timeout: timedelta = timedelta(seconds=60)
class AnthropicConfig(BaseModel, extra="forbid"): api_key: SecretStr; model: str
class ServerConfig(BaseModel, extra="forbid"):    bind: str = "127.0.0.1:8080"; base_url: HttpUrl; max_request_bytes: int = 1_048_576; rate_limit_per_minute: int = 120; bridge_interval: timedelta = timedelta(milliseconds=250)
class HeartbeatConfig(BaseModel, extra="forbid"): interval: timedelta = timedelta(seconds=30)
class StoreConfig(BaseModel, extra="forbid"):     sqlite_path: Path = Path("tiny-harness.sqlite3")
class O11yConfig(BaseModel, extra="forbid"):      otlp_endpoint: HttpUrl | None = None; langfuse_public_key: SecretStr | None = None; langfuse_secret_key: SecretStr | None = None
class RetryPolicySpec(BaseModel, frozen=True):    initial_interval: timedelta = timedelta(seconds=1); backoff_coefficient: float = 2.0; maximum_interval: timedelta = timedelta(seconds=60); maximum_attempts: int = 5; non_retryable_error_types: tuple[str, ...] = ()
class RetryPolicies(BaseModel, extra="forbid"):   default: RetryPolicySpec; per_activity: Mapping[str, RetryPolicySpec] = {}
class ContextConfig(BaseModel, extra="forbid"):   turn_budget_tokens: int = 12_000; compaction_fraction: float = 0.75; history_event_bound: int = 10_000
class Settings(BaseSettings, extra="forbid"):
    temporal: TemporalConfig; openai: OpenAIConfig; anthropic: AnthropicConfig | None = None
    server: ServerConfig; heartbeat: HeartbeatConfig = HeartbeatConfig()
    plugins: tuple[Path, ...] = (); store: StoreConfig = StoreConfig(); o11y: O11yConfig = O11yConfig()
    retries: RetryPolicies; context: ContextConfig = ContextConfig()
    push_key: SecretStr                  # TINY_HARNESS_PUSH_KEY, 32 bytes base64
    retention: RetentionConfig = RetentionConfig()   # ttl per record kind, default 30 days
```

Intrinsic tools and their input schemas (decision-004), each a `ToolDefinition` with
`execution=INTRINSIC` registered by the built-in plugin: `create_plan(steps: [{name,
description, depends_on}])`, `complete_step(step_id, output)`, `spawn_subtask(agent: str |
null, name, goal, acceptance_criteria)`, `ask_participant(participant_id, question,
options)`, `create_task_for_participant(participant_id, name, goal, acceptance_criteria)`,
`set_participant_role(participant_id, role)`, `list_skills()`, `load_skill(name)`,
`unload_skill(name)`, `list_skill_resources(name)`, `load_skill_resource(name, path)`,
`emit_ui(messages: A2UI server messages)`. Their JSON schemas are generated from Pydantic
argument models and committed with the extension schemas.

`pydantic-settings` reads environment variables; a missing required secret fails
`Settings()` at startup with the variable name (21.2); unknown keys are rejected (21.3).
The e2e `.env.example` documents the two `secret-tool` lookups (21.1).

### Requirement → component map

| Requirement | Components |
|---|---|
| R1 | `entities/` (`EntityRef`, `Registry`, `RemoteLocation`) |
| R2 | `hooks/` (`HookPoint`, contexts, `HookManager`, local, JSON-RPC and MCP executors), activity wrapper |
| R3 | `plugins/` (`PluginLoader`, manifest models, namespace dir), `builtin/` |
| R4 | `prompts/`, `builtin/systemprompt.md` |
| R5 | `skills/` (`SkillLoader`, `Skill`), skill intrinsics |
| R6 | `tools/` (`Tool`, `McpToolSource`, validation, idempotency) |
| R7 | `agents/remote.py`, `RemoteTaskWorkflow`, `spawn_subtask` |
| R8, R9 | `core/task.py`, `core/plan.py`, task extension |
| R10 | `core/context.py`, `core/compaction.py` |
| R11 | `persistence/` (`Store`, `SqliteStore`) |
| R12, R13 | `channels/`, `A2AChannel`, channel extension, `ask_participant`, `create_task_for_participant` |
| R14 | `service/a2a/` (`HarnessExecutor`, card builder, `EventBridge`, `TemporalTaskStore`, middleware) |
| R15 | `service/inbox.py`, `TaskWorkflow.inbox` |
| R16 | `service/heartbeat.py`, `HeartbeatWorkflow`, schedule |
| R17 | `service/o11y/` plugin, `Redactor` |
| R18 | `models/` (`LLM`, `OpenAILLM`, `AnthropicLLM`, `SystemOne`, `FakeSystemOne`) |
| R19 | `service/durable/` (workflows, activities, worker, retry policies) |
| R20 | `interaction/` (surface, renderer, `tui/`, `a2ui/`), `renderers/web` on `@a2ui/react` |
| R21 | `config.py`, `.env.example` |
| R22 | package layout above; pyright strict; boundary parsers in each adapter |
| R23 | `tests/contract/` per interface; JSON schemas for extensions |
| R24 | `examples/demo/` (plugin with two MCP tools, demo script), evidence |

## UI/UX design

| Artifact | Type | Location / link | Covers (screen · requirement) | Status |
|----------|------|-----------------|-------------------------------|--------|
| `design/web-renderer.html` | html-prototype | `docs/specs/issue-3/design/web-renderer.html` (open the file in a browser; not routed by the docs site) | Web chat: event stream, tool calls, A2UI card with ChoicePicker and Button, help request, placeholder, task/plan/trace pane · R20, R12, R24 | draft |
| `design/tui-renderer.html` | html-prototype | `docs/specs/issue-3/design/tui-renderer.html` (open the file in a browser; not routed by the docs site) | TUI: the same states as Textual panes and key bindings · R20, R12, R24 | draft |

Screenshots of the drafts (rendered with headless Chromium, both themes, phone width):
`design/screenshots/web-renderer-{light,dark,phone}.png`,
`design/screenshots/tui-renderer-{light,dark,phone}.png`.

- **Flows & states.** One task from submission to `INPUT_REQUIRED` and back: user message
  → status update → tool calls → agent message → A2UI card → help request → reply on the
  channel → `WORKING`. Both prototypes simulate the reply and the A2UI action locally.
  States shown: `WORKING`, `INPUT_REQUIRED`; the pill also renders `COMPLETED`,
  `FAILED`, `CANCELED`, `REJECTED`, `AUTH_REQUIRED` with the same component.
- **Design system / tokens.** Six colour tokens per theme (`--bg`, `--panel`/`--term`,
  `--fg`, `--muted`, `--rule`, `--accent`) plus `--warn`/`--err` for task states, defined
  on `:root` with dark overrides under `prefers-color-scheme` and `data-theme`. System
  sans and monospace stacks; no web fonts, no external assets. The web app reuses the
  tokens as CSS variables; the TUI maps them to a Textual theme.
- **Accessibility & responsiveness.** Web: two panes above 820 px, stacked below; tab
  list and radio group semantics with `aria-selected`/`aria-pressed`; visible focus
  rings; 16 px gutters; no horizontal scroll at 400 px. TUI: every action has a key
  (Tab, F2, Enter, ^C, q); the A2UI ChoicePicker is a Textual `RadioSet`; unrenderable
  parts are announced as text.
- **Evidence.** The screenshots above are of the drafts; the locked set is re-captured
  when the designer (the owner, who holds the role) signs off at `design-approval`.

## Data models

Models are Pydantic v2, `extra="forbid"` unless the specification says unknown keys are
allowed, and shared by workflows (through the Pydantic data converter), the store (JSON
columns), the extensions (JSON schemas generated by `model_json_schema()` and committed
under `docs/a2a/ext/`) and the renderers (TypeScript types generated from the same
schemas at build time, `json-schema-to-typescript`).

```mermaid
classDiagram
  class Task { a2a.types.Task: id; context_id; status; artifacts; history; metadata[TASK_EXT_KEY] }
  class TaskExtensionData { name; type; goal; acceptance_criteria; participants; parent_tasks; sub_tasks; plan }
  Task "1" --> "1" TaskExtensionData : metadata
  class Plan { steps }
  class Step { id; depends_on; output; linked_tasks; state }
  class Participant { id; kind; role }
  class Channel { id; task_id; members }
  class ChannelMessage { id; sender; parts; at }
  class AgentState { task_id; history; summary; loaded_skills; data: SchemaValidated }
  class ContextWindow { sections; tools; estimated_tokens }
  class CompactionRecord { removed_ids; summary; tokens_before; tokens_after }
  TaskExtensionData "1" --> "0..1" Plan
  Plan "1" --> "*" Step
  Task "1" --> "*" Participant
  Task "1" --> "*" Channel
  Channel "1" --> "*" ChannelMessage
  Task "1" --> "1" AgentState
  AgentState --> ContextWindow : assembled into
  AgentState "1" --> "*" CompactionRecord
```

- **Agent state (10.1).** `AgentState.data` is `SchemaValidated`: a JSON object plus the
  `(schema_id, schema)` a plugin registered for a named subset; writes to that subset are
  validated by `jsonschema` before the activity returns.
- **Task extension schema** (`application/vnd.tiny-harness.task+json`):
  `TaskExtensionData` as above, `additionalProperties: false`.
- **Event envelope schema** (`application/vnd.tiny-harness.event+json`, part of the task
  extension): `EventEnvelope(kind, payload)` where `payload` is `TaskExtensionData`, or
  the ProtoJSON of a `TaskStatusUpdateEvent` or `TaskArtifactUpdateEvent`.
- **Channel extension schema** (`application/vnd.tiny-harness.channel+json`):
  `ChannelMessageData(channel_id, sender, text, parts, kind: "message" | "help_request" | "help_reply")`.
- **Temporal search attributes.** `A2AContextId` (keyword), `A2ATaskState` (keyword),
  `TinyHarnessAgent` (keyword), registered by the worker at startup.
- **Store tables.** `tasks`, `plans`, `state`, `channel_messages`, `inbox_audit`,
  `compactions`, `push_configs`; each `(id TEXT PRIMARY KEY, context_id TEXT, created_at TEXT, json
  TEXT)` with indexes on `context_id` and `created_at`.

## Error handling

One typed hierarchy, every error carrying a machine-readable `code` and never a secret:

```text
TinyHarnessError
├── EntityNotFoundError, VersionNotFoundError, RegistryConflictError       (R1)
├── HookAbort(reason), HookTransportError                                   (R2)
├── PluginError(manifest_path), ComponentSkipped(reason)                     (R3)
├── SkillError                                                               (R5)
├── ToolNotFoundError, ToolArgumentError(validation), ToolNotRetriedError,   (R6, R19)
│   ToolSchemaChangedError
├── PlanCycleError                                                           (R9)
├── StoreWriteError                                                          (R11)
├── ChannelMembershipError                                                   (R13)
├── UnsupportedExtensionError                                                (R7, R14)
├── ConfigError(variable)                                                    (R21)
└── RetryableProviderError(provider, status)                                 (R18)
```

| Where | Failure | Surfaced as |
|---|---|---|
| Activity body | provider 429/5xx, network | `RetryableProviderError` → workflow-managed retry per `RetryPolicySpec`; `activity.failed`/`activity.retried` hooks between attempts |
| Activity body | `HookAbort` | `ApplicationError(non_retryable=True)` → the loop records the abort; task `FAILED` or the step marked refused, per `reason` |
| `invoke_tool` | tool not in registry, arguments invalid | error `ToolResult` back to the LLM, no retry |
| `invoke_tool` | non-idempotent tool failed | `ToolNotRetriedError` as error `ToolResult`; a hook may re-issue |
| Workflow | cancel signal | activities cancelled, `CANCELED` emitted, store updated |
| Server | malformed or oversized request | A2A JSON-RPC error before intake, nothing persisted |
| Server | unadvertised extension | A2A `UnsupportedOperationError` |
| Startup | missing secret, unknown key | `ConfigError` with the variable name, process exits non-zero |
| Heartbeat | tick failure | workflow run fails, logged, schedule continues |

Every row logs through the o11y plugin at the same level in development and production
(`reference/observability.md`): one structured record with `task_id`, `correlation_id`,
`operation`, `phase`, `code`, and the span records the exception.

## Security design

Each boundary from the requirements' Security considerations, the mechanism, and the test
that proves it. Abuse cases are numbered as in `requirements.md`.

- **AuthN/AuthZ.** None in the harness (decision-003): the perimeter authenticates, and
  participant identity is `Message.metadata["participant_id"]` (or the `X-Participant-Id`
  header the perimeter may set), **self-asserted** until the later authentication work
  item binds it to `ServerCallContext.user`. One `AccessPolicy` is applied at every
  task-access boundary in `HarnessRequestHandler`: `GetTask`, `ListTasks` (filtered to the
  caller's tasks), `SubscribeToTask`, `CancelTask`, the four push-config operations, and
  `SendMessage` to an existing task. The rule: the asserted participant must be a
  participant of the task; otherwise the response is the uniform A2A task-not-found error
  (abuse case 4), identical for a missing task and a foreign one. Channels add membership
  (`ChannelMembershipError`). Role changes exist only through the `set_participant_role`
  intrinsic and the task extension on `SendMessage`, and both require the asserted
  participant to hold `ADMIN` (abuse case 2); any other privileged act (cancel) requires
  participation. Denials are recorded. The deployment guide names the perimeter requirement; the agent card
  declares no security scheme, so no client is told it can authenticate.
- **Input validation & injection surfaces.**
  - *A2A ingress*: the SDK parses the protocol types; a Starlette middleware enforces
    `max_request_bytes` (default 1 MiB) and a token-bucket rate limit per peer address
    before the request reaches a route, so nothing oversized is persisted (abuse
    case 7).
  - *Prompt injection* (abuse case 2): tool results, remote-agent messages, channel
    messages and A2UI actions are rendered only inside delimited untrusted blocks with a
    fixed preamble; the only effect text can have is through a tool call the LLM emits,
    which must name a registered tool and validate against its schema (`ToolNotFoundError`,
    `ToolArgumentError`); role changes exist only as the `set_participant_role` intrinsic
    and the task extension, both admin-only as above.
  - *Command injection* (abuse case 3): an MCP `command` containing `${` is rejected at
    load with `PluginError`; `args`, `env`, `cwd` expand two fixed variables; subprocesses are started with an argument vector,
    never a shell; `cwd` and every component path must resolve inside the plugin root.
  - *Path traversal*: same resolution rule for skills' `references/`, `assets/`,
    `scripts/` (one level deep, inside the skill directory).
  - *Schema drift* (abuse case 8): `McpToolSource` compares the schema hash at call time.
  - *A2UI actions* (abuse case 9): an action's `surfaceId` and `sourceComponentId` must
    exist in the task's emitted surfaces; otherwise discarded and logged.
  - *Remote agent cards* (abuse case 5): a card with an unknown required extension or any
    declared security scheme is refused by `RemoteAgent` until a later work item adds
    credential handling; nothing is sent.
- **Secrets handling.** All secrets are `SecretStr` in `Settings`, read from the
  environment. The `Redactor` (`harness/security/redactor.py`: bearer tokens, `sk-` and
  `tmprl` key shapes, `Authorization` headers, any value equal to a configured secret)
  runs at four points so no credential-shaped string is ever recorded (abuse case 6):
  (1) in `execute`, over every text and data part of the inbound message **before**
  update-with-start, so the update argument in Temporal history is already redacted;
  (2) in the workflow's activity wrapper, over every activity argument before scheduling
  and over every result before it is returned to the workflow, so history holds redacted
  payloads; (3) in the `persist` activity over every `Record`; (4) in the o11y plugin
  over log fields and span attributes. The one credential the harness must keep is the
  A2A push-notification config's `token`/`authentication`, a client-supplied callback
  secret: `PushConfigRecord` stores it encrypted (AES-GCM through `cryptography`, key
  from `TINY_HARNESS_PUSH_KEY`), it is decrypted only inside the `emit_event` activity,
  and it is never placed in a workflow payload. Secrets never appear in the context
  window: the LLM request carries no configuration.
- **Least privilege.** The worker needs the Temporal namespace, the provider key and the
  store file; the server needs the Temporal namespace and the store file, no provider
  key; MCP subprocesses inherit only `PLUGIN_ROOT`, `PLUGIN_DATA` and the `env` the
  manifest declares, not the parent environment; renderers hold no secret at all.
- **Data retention** (the personal-data boundary of the requirements). `RetentionConfig`
  (in `Settings`) sets a TTL per store record kind (default 30 days for every kind;
  `tasks` and `plans` measured from the terminal state), and the heartbeat workflow's
  `retention_sweep` activity deletes expired rows on every tick. Temporal history
  retention is the namespace's setting on Temporal Cloud (the deployment guide names it;
  the demo namespace uses the default 30 days, after which Temporal deletes closed
  workflows). Trace retention belongs to the OTLP backend (Langfuse's project setting),
  named in the guide. `tiny-harness tasks purge <task-id>` deletes a task's rows from the
  store and terminates its workflow, for a deletion request that cannot wait for the TTL.
- **Fail-closed behaviour.** Missing secret or Temporal config: `ConfigError`, exit.
  Unresolvable entity, unknown hook point, manifest error: typed error, no default.
  Non-idempotent tool with an unclear policy: `maximum_attempts=1`. Ambiguous participant
  role: deny. Unreachable remote hook: activity failure through the retry policy, never
  pass-through. No perimeter: documented as the operator's responsibility.
- **Abuse-case coverage.**

| Abuse case | Mechanism | Negative test (testing-plan row: security) |
|---|---|---|
| 1 unauthenticated client | perimeter (out of scope) | documented; no harness test |
| 2 injected instructions | untrusted blocks + registry + schema + admin-only role change | `test_injected_tool_call_not_executed`, `test_role_change_requires_admin` |
| 3 unregistered tool / path escape / `command` expansion | `ToolNotFoundError`, path resolution, `${` in `command` rejected at load | `test_unknown_tool_rejected`, `test_plugin_path_escape_rejected`, `test_command_with_expansion_rejected` |
| 4 non-member on channel / foreign task | `AccessPolicy` on every task operation + channel membership, uniform not-found | `test_non_member_rejected_without_task_existence`, `test_foreign_task_get_list_subscribe_cancel_not_found` |
| 5 unknown required extension / security scheme on remote card | `RemoteAgent` refusal | `test_remote_card_with_unknown_required_ext_refused` |
| 6 credential-shaped values | `Redactor` at ingress, activity boundary, store and o11y; push tokens encrypted | `test_redactor_masks_tokens`, `test_ingress_redacted_before_history`, `test_push_token_encrypted_at_rest` |
| 7 oversized / rate-limited request | middleware limits before any route or Temporal call | `test_oversized_request_not_persisted` |
| 8 tool schema drift | schema hash check | `test_schema_drift_refuses_invoke` |
| 9 forged A2UI action ids | surface/component registry | `test_unknown_a2ui_action_discarded` |

## Testing strategy

Unit tests cover each entity, loader, model adapter and the context window manager with
fakes (`FakeLLM`, `FakeSystemOne`, an in-memory `Store`, a scripted MCP server over
stdio), asserting through public interfaces only. Contract tests under `tests/contract/`
pin every signature in this document: the entity and hook interfaces (an `inspect`-based
snapshot of the public API), the hook-context and configuration JSON schemas, and the two
A2A extension schemas validated against committed fixtures. Integration tests run the
workflows in Temporal's time-skipping test environment with real activities against the
fakes, the A2A server in-process with the `a2a-sdk` client, and the plugin loader against
fixture plugins; each carries a Gherkin docstring (`Feature: Durable core loop`,
`Scenario: a worker crash mid-activity resumes without a second LLM call`; `Feature: A2A
server`, `Scenario: an unadvertised extension is rejected`; `Feature: Help requests`,
`Scenario: a reply on the channel resumes an INPUT_REQUIRED task`). The security table
above is the abuse-case suite. The e2e demo of Requirement 24 runs against Temporal Cloud
and `gpt-6.1-sol` with both renderers, captures screenshots and the multi-turn flow, and
kills the worker mid-task; its trace is the evidence that no LLM or tool call ran twice.
Which types apply, the environment and the evidence plan are `testing-plan.md`'s.

## Trade-offs & decisions

- **Temporal everywhere** (decision-002): durability and one mechanism, at the cost of
  Temporal as a hard dependency for local development and ~250 ms streaming latency.
- **No authentication** (decision-003): speed and enterprise fit, at the cost of a
  self-asserted participant identity until the next work item.
- **Intrinsics as tools** (decision-004): a five-line loop and one enforcement point, at
  the cost of relying on the LLM to call `create_plan` rather than forcing a plan phase;
  the `plan.created.in` default runs on the first turn of a task so a plan always exists.
- **Own loaders for Skills and Plugins**: the reference implementations are demo-grade
  or absent; two small parsers against published schemas cost less than an untyped
  dependency.
- **SQLite by default**: standard library, zero setup; replaced by a store entity in
  production.
- **Polling event bridge**: no broker; a plugin can replace it.
- **TypeScript types generated from the Python schemas**: one source of truth for the
  extensions across both renderers.
- **A2UI 0.9.1 with vendored schemas**: follows the approver's rule and avoids a
  dependency that breaks against `a2a-sdk` 1.x; moving to 1.0 later is a schema swap and
  a URI change.

### sherma: reused and replaced

| sherma | tiny-harness | Why |
|---|---|---|
| `Agent.send_message` / `cancel_task` / agent card | reused as `Agent` | ticket's chosen API |
| `Registry[T]`, `RegistryEntry[T]`, PEP 440 resolution | reused; one registry, typed `get`, `version: str \| None`, no `tenant_id` | R1.2, scope |
| `HookManager` chain, context-replacement semantics | reused | R2.5 |
| 20 hook names | kept where the lifecycle matches, renamed to `operation.phase`, extended | R2.1, R2.8 |
| remote hooks: JSON-RPC and MCP | reused; pass-through on error removed | R2.6 |
| `before_tool_call` on the tool set | per-call `ToolInvokedPre` | R2.9 |
| A2A executor (`a2a-sdk` 0.3) | ported to 1.x; card built from the entity; streaming | R14 |
| LangGraph graph, declarative YAML, CEL | not carried over | the loop is the ticket's pseudo-code; plugins replace YAML |
| LangChain model wrappers, `langchain-mcp-adapters` | official `openai`, `anthropic`, `mcp` SDKs | R22.4 |
| skill tools (list/load/unload/resources) | reused as intrinsics | R5.6 |
| `MemorySaver` checkpointer | Temporal history + `Store` | R11, R19 |
| no compaction | `ContextWindowManager` + `compaction.in` | R10.8 |

### Dependencies (minimalism ladder)

| Dependency | Rung 1–5 could not | Justification |
|---|---|---|
| `a2a-sdk[http-server]` | protocol types, server, client | R22.4; the protocol is the product's surface |
| `mcp` | MCP client, transports, OTel middleware | R22.4 |
| `temporalio[pydantic,opentelemetry]` | durable execution | R19 |
| `openai`, `anthropic` | provider SDKs | R22.4 |
| `pydantic`, `pydantic-settings` | typed models everywhere; env settings | R22.2; already pulled by `mcp` |
| `jsonschema` | validate tool arguments and state subsets against JSON Schema | stdlib has no validator |
| `opentelemetry-sdk`, `-exporter-otlp` | traces | R17 |
| `cryptography` (via `a2a-sdk[encryption]`) | AES-GCM for push-config tokens at rest | finding 1; stdlib has no AEAD |
| `textual` | TUI | R20.2 |
| `packaging` | PEP 440 resolution | transitive via `openai`, used directly |
| `pyyaml` | skill and prompt front matter | already a dev dependency; `tomllib` cannot parse YAML |
| `a2ui-agent-sdk` (Python) | **not added**: incompatible with `a2a-sdk` 1.x and pulls `google-adk`; the harness emits payloads itself against the vendored 0.9.1 schemas | R20.5, A2A ≥ 1.0 |
| `@a2ui/react`, `@a2ui/web_core` (web) | the official A2UI React renderer and default catalog | R20.5–20.6 |
| `typesafe-sdk` | **not added**: the interface only, no client in this work item | Q3 answer |
| `langfuse` | **not added**: OTLP export reaches Langfuse | R17.5 |
| `react`, `vite`, `typescript` (web) | web renderer | R20.2 |
| `@a2a-js/sdk` (web) | the official A2A JavaScript SDK's client: card resolution, JSON-RPC and HTTP+JSON transports, streaming | R20.2, R22.4; replaces the hand-written REST+SSE client of Layer 8 |

### Stacked pull requests

The approver chose stacked PRs (Q1). The task DAG cuts the work into layers, each a PR
against the previous one, merged in order:

1. `entities`, `hooks`, `config`, `errors`, contract-test scaffold.
2. `plugins`, `prompts`, `skills`, `builtin/` skeleton.
3. `models` (OpenAI, Anthropic, System One interface and fake), `tools` (MCP, intrinsics).
4. `core` (task, plan, state, context, compaction) and `persistence`, with the loop run in
   Temporal's test environment.
5. `service/durable`, `service/a2a`, `inbox`, `heartbeat`, `channels`.
6. `service/o11y`.
7. `interaction/a2ui`, `interaction/tui`.
8. `renderers/web`.
9. `examples/demo`, docs site pages, capability docs, the e2e run.

## Open questions

For the design-approval gate (raised by the design critic round, recorded in
`evidence/design-critic-review.md`):

1. **R22.4 and A2UI.** Requirement 22.4 names A2UI among the constructs that must use
   the official SDK. The design uses the official A2UI renderer (`@a2ui/react` with
   `@a2ui/web_core` and its default catalog) on the web, but not the Python agent-side
   `a2ui-agent-sdk`, which imports the 0.3.x A2A types and fails against `a2a-sdk` 1.2;
   the harness emits payloads itself against the vendored 0.9.1 schemas. **Asked:** record
   that reading of R22.4 (official renderer yes, agent SDK no, A2A ≥ 1.0 untouched).
   Default if unanswered: recorded.
2. **R24.5 crash points.** The design states the at-least-once window for a provider call
   when a worker dies between the provider's reply and Temporal recording it, and proves
   "no duplicated LLM or tool call" at the demo's two kill points (idempotent tool
   activity; `INPUT_REQUIRED` wait). **Asked:** confirm that narrowing. Default if
   unanswered: confirmed.

The A2UI version rule (Q7) resolves to 0.9.1 on the installed-package facts above.

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.

### 2026-10-09 — approved

**@MadaraUchiha-314** wrote:

approved design
