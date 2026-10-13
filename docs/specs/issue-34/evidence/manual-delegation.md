# T11 — manual run with a real model

**Result: pass.** A real model (`gpt-6.1-sol`) read the agents roster and delegated to
the configured agent by itself. Nobody named the agent or its id. The agent answered,
and the model replied to the user with that answer.

Run on 2026-10-13 at commit `1e92d8b`. Embedded Temporal, everything on `127.0.0.1`.
`OPENAI_API_KEY` came from the environment. It is not in this file.

## Set-up

- **Agent B** (`127.0.0.1:8091`): a stand-in A2A 1.0 agent built on `a2a-sdk`. Source
  below. Its card says "Order ledger", with the skill `lookup-order`.
- **Harness A** (`127.0.0.1:8090`): `examples/demo` (its plugin, its model) with this
  configuration. Paths to the session scratch folder are shown as `<scratch>`.

```toml
plugins = ["examples/demo"]
agents = [{ id = "ledger", url = "http://127.0.0.1:8091" }]

[temporal]
mode = "embedded"
task_queue = "t11-issue-34"

[openai]
model = "gpt-6.1-sol"
timeout = "PT120S"
max_output_tokens = 2000

[server]
bind = "127.0.0.1:8090"
base_url = "http://127.0.0.1:8090"

[store]
sqlite_path = "<scratch>/state/tiny-harness.sqlite3"

[o11y]
log_level = "INFO"
trace_file = "<scratch>/state/trace.jsonl"
```

- **Request:** one JSON-RPC `SendMessage` to A as participant `alice`:
  "What is the status of order 48213?" It does not name an agent.

## What happened

1. A's startup log names the roster:

   ```json
   {"level": "INFO", "logger": "tiny_harness.runtime", "msg": "agents roster: ledger", "ts": "2026-10-13T07:57:58.340806+00:00"}
   ```

2. The model called `spawn_subtask` (trace span `execute_tool spawn_subtask`,
   `tiny_harness.tool.command: spawn_subtask`). The sub-task record on the parent task
   names agent `ledger`:

   ```json
   [
     {
       "sub_state": null,
       "task_id": "1ee93cc0-ecc8-4c10-a97d-85787be6d2d0.1",
       "agent": {
         "id": "ledger",
         "version": null,
         "kind": "agent"
       },
       "state": "COMPLETED"
     }
   ]
   ```

3. Agent B received a self-contained goal written by the model (B's log):

   ```text
   ledger received: 'Look up order 48213 in the order ledger and return its verified current status and any available delivery or shipment details. This is an informational request only; do not issue refunds or ship anything.'
   ```

4. The parent task heard the result and answered alice. Final status of the parent task
   (`INPUT_REQUIRED`, awaiting alice's next message):

   ```text
   Order **48213** shipped by courier on **October 10, 2026** and is expected to arrive on **October 14, 2026**.
   ```

The trace has 6 `chat gpt-6.1-sol` spans and one `CompleteWorkflow:RemoteTaskWorkflow`
span.

## Note on the first attempt

On the first attempt the model also delegated to `ledger`, unprompted. The
stand-in agent B then failed: it sent a status update before it enqueued its task, and
`a2a-sdk` refused it (`INVALID_AGENT_RESPONSE`). That was a bug in the stand-in, not
in tiny-harness. The stand-in was fixed (it now enqueues the task first) and the run
above is the second attempt, with fresh state.

## Agent B source

```python
"""T11 stand-in agent B: an A2A 1.0 agent whose card says what it does."""

import uvicorn
from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part
from starlette.applications import Starlette

URL = "http://127.0.0.1:8091/"
CARD = AgentCard(
    name="Order ledger",
    description="Answers order status and refund questions from the order ledger.",
    version="1.0.0",
    supported_interfaces=[AgentInterface(url=URL, protocol_binding="JSONRPC", protocol_version="1.0")],
    capabilities=AgentCapabilities(streaming=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="lookup-order",
            name="lookup-order",
            description="Looks up an order's status and refund state by order number.",
        )
    ],
)
SEEN: list[str] = []


class Ledger(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        SEEN.append(text)
        print(f"ledger received: {text!r}", flush=True)
        if context.current_task is None:
            await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.complete(
            updater.new_agent_message(
                [Part(text="Order 48213: shipped 2026-10-10 by courier, arriving 2026-10-14. No refund open.")]
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


handler = DefaultRequestHandler(agent_executor=Ledger(), task_store=InMemoryTaskStore(), agent_card=CARD)
app = Starlette(routes=[*create_agent_card_routes(CARD), *create_jsonrpc_routes(handler, rpc_url="/")])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8091, log_level="warning")
```
