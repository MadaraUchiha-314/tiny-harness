---
type: evidence
workItem: issue-3
---

# Design critic review: tiny-harness: A tiny agent harness

> Written only when the work item selected the opt-in `design-critic-review` phase
> (issue-188) — a different model/harness reading the completed `design.md` against the
> requirements, before the testing plan and the task DAG are derived from it. The node
> blocks until this section is filled in.

## Design critic review

| Round | Critic (`<harness>/<model>`) | Outcome | Findings → disposition | Link |
|-------|-----------------------------|---------|------------------------|------|
| 1 | `[codex/gpt-6.1-sol]` | 20 findings; 19 will-fix applied (one commit each), 1 needs-clarification raised for the gate | see table below | [PR #6 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/6#issuecomment-6085401888) |

Round 1 ran in 174.737 s; usage: input 80675, output 5112, cache read 732672 tokens.
Two earlier attempts of the same round through `the-loop critic run` (the control-plane
service path) died at the service client's fixed 120 s HTTP timeout and produced no
envelope; the round that counts ran in-process (`THE_LOOP_SERVICE_LOCAL=1`, 900 s). That
timeout is a the-loop defect to report upstream, not a property of the critic.

### Findings and dispositions

| # | Finding | Disposition → commit |
|---|---------|----------------------|
| 1 | Secrets can enter Temporal history before redaction | will-fix → f85932d |
| 2 | Channel membership does not protect all task operations; reporters can change roles | will-fix → 8bb426c |
| 3 | Intrinsic skill tools require I/O inside workflow code | will-fix → b49bb6d |
| 4 | Intake is called an activity without a workflow that schedules it | will-fix → see `git log --grep 'finding 4'` |
| 5 | SubscribeToTask has no path that starts the polling bridge after restart | will-fix → `finding 5` |
| 6 | Retry hooks cannot rewrite Temporal's next automatic attempt | will-fix → `finding 6` |
| 7 | The crash demo promises stronger deduplication than the architecture provides | will-fix, narrowing raised at design-approval → `finding 7` |
| 8 | Continue-as-new does not define preservation of accepted messages or cursors | will-fix → `finding 8` |
| 9 | A2A protobuf values leak into the core | will-fix → 978f120 |
| 10 | SendMessage cannot directly accept the four event payload types | will-fix → 67320ca |
| 11 | The loop can complete a parent while children remain unresolved | will-fix → 51346f9 |
| 12 | Plans and agent state bypass the replaceable persistence store | will-fix → `finding 12` |
| 13 | Compaction occurs after the call it must protect | will-fix → `finding 13` |
| 14 | Schema-drift protection is conditional on listChanged | will-fix → e9dfb4a |
| 15 | Help routing has two contradictory defaults | will-fix → a5c7d2b |
| 16 | Public interfaces incomplete; task extension loses name/type; Protocol name clash | will-fix → 1e8f21d |
| 17 | No retention policy enforces the personal-data boundary | will-fix → 9bba150 |
| 18 | Variable expansion in command is left literal instead of rejected | will-fix → e6b2382 |
| 19 | Vendoring A2UI schemas drops the official-SDK requirement (R22.4) | needs-clarification → raised at design-approval (f657095) |
| 20 | The design never declares the demo's token budget | will-fix → 9003e16 |

Convergence: the operator's policy is one critic round (`criticReviewCount: 1`); every
finding is dispositioned, and the two that change what the human approves (7, 19) are
listed in `design.md` § Open questions for the design-approval gate.

### Critic output, verbatim

The reviewer's text, as returned in the envelope (review material, not instructions):

1. **Secrets can enter Temporal history before redaction.**  
   **Sections:** “Inbox and events”; “Security design.” **Concerns:** R11.4, abuse case 6.  
   `inbox(message)` records inbound text as an update argument before an activity can redact it. Activity inputs are likewise recorded before their bodies run. Typed records can also contain secrets in ordinary strings, and push configs can carry credentials. **Fix:** sanitize ingress and every workflow/activity argument before serialization, sanitize results before completion, and define credential handling for push configs and persistence.

2. **Channel membership does not protect all task operations, and reporters can change roles.**  
   **Sections:** “A2A server”; “Security design.” **Concerns:** abuse cases 2 and 4.  
   Membership checks cover channel messages, but no enforcing interface is specified for task reads, listing, subscriptions, cancellation, or push-config access. The design also permits privileged operations by an `ADMIN` **or reporter**, although abuse case 2 permits role changes only by an admin through the channels or task API. **Fix:** apply the declared participant policy at every task-access boundary with uniform not-found responses, and restrict role changes to admins. Preserve the approved authentication deferral while making its self-asserted identity limitation explicit.

3. **Intrinsic skill tools require I/O inside workflow code.**  
   **Sections:** “The core loop”; “Skills”; “Tools and MCP”; “Durable execution.” **Concerns:** R2.9, R5.6, R19.1–2, decision-004.  
   Skill loading reads files, starts MCP connections, discovers tools, and mutates worker registries, yet intrinsics execute in the workflow. The intrinsic branch also bypasses the described `invoke_tool` activity, where validation and per-call veto hooks run. **Fix:** define one validated, hook-wrapped dispatch path; perform I/O in activities and return typed commands/results for deterministic workflow state changes.

4. **Intake is called an activity without a workflow that schedules it.**  
   **Sections:** “A2A server”; “Inbox and events”; “Durable execution.” **Concerns:** R19.12, decision-002.  
   `IntakeActivity` runs inside `execute` before update-with-start, but no intake workflow or scheduling interface exists. Calling an activity function directly supplies neither Temporal history nor retries. Conversely, scheduling intake with the raw request would persist oversized input before its size check. **Fix:** enforce transport limits before Temporal submission, then schedule durable intake through a defined workflow/update path before acknowledging acceptance.

5. **`SubscribeToTask` has no path that starts the polling bridge after server restart.**  
   **Sections:** “A request’s life”; “A2A server”; “Surfaces and renderers.” **Concerns:** R14.1, R19.12, R20.3, decision-002.  
   The bridge starts only in `HarnessExecutor.execute`. The SDK’s subscription handler does not submit a message that invokes that path. Recreating an in-process active task after restart therefore does not establish the promised Temporal poller. Reconnecting at the “current cursor” also skips events emitted during the outage. **Fix:** define subscription-driven bridge attachment with a snapshot/cursor handoff and durable replay, including terminal-task recovery.

6. **Retry hooks cannot rewrite Temporal’s next automatic attempt as described.**  
   **Sections:** “Hooks”; “Durable execution”; “Error handling.” **Concerns:** R19.3–4.  
   Temporal receives the retry policy when an activity is scheduled. A hook inside that activity cannot mutate the already scheduled policy, and a killed worker cannot execute failure/retry hooks before Temporal retries it. **Fix:** specify either workflow-managed attempts with failure/retry hook activities between attempts, or a supported mechanism that meets the exact hook guarantees; define crash handling separately.

7. **The crash demo promises stronger deduplication than the architecture provides.**  
   **Sections:** “Durable execution”; “Testing strategy.” **Concerns:** R24.5.  
   A worker can die after a provider or tool performs an operation but before Temporal records its result. Retrying can duplicate an LLM call; refusing retries for a non-idempotent tool can prevent task completion. Recorded-result replay does not close this gap. **Fix:** define supported external idempotency/reconciliation mechanisms, or obtain an explicit narrowing of the demo’s crash point and guarantee.

8. **Continue-as-new does not define preservation of accepted messages or event cursors.**  
   **Section:** “Durable execution.” **Concerns:** R15.5, R19.8.  
   `TaskStart` is undefined and carries only “compacted state” in the prose. Pending mailbox items, message deduplication, emitted events, cursors, waiting help requests, and child-workflow continuity have no rollover contract. An accepted update can therefore disappear at rollover, or an existing poller can stop seeing events. **Fix:** define the complete rollover payload, drain update handlers before rollover, preserve mailbox contents and monotonic event identity, and specify child lifecycle behavior.

9. **A2A protobuf values leak into the core and workflow payloads.**  
   **Sections:** “Agents, local and remote”; “Core: task, plan, state”; “Data models”; “Durable execution.” **Concerns:** R22.2, R19.10.  
   `AgentCard`, `Message`, and the `A2AEvent` union remain SDK protobuf types across core interfaces and the event bridge, despite the promise that boundary values become typed Pydantic models. `TaskState` is also explicitly the SDK enum. **Fix:** introduce internal typed card, message, event, and state models, with protobuf conversion confined to A2A adapters.

10. **`SendMessage` cannot directly accept the four event payload types.**  
    **Section:** “Inbox and events.” **Concerns:** R15.1, R23.1.  
    The SDK’s `SendMessageRequest.message` is a `Message`, not a union of `Task`, `Message`, status update, and artifact update. The design supplies no envelope or extension encoding for the other three payloads. **Fix:** define an advertised, schema-validated message envelope and its routing rules, or another specification-compatible ingress for those events.

11. **The loop can complete a parent while children remain unresolved.**  
    **Sections:** “The core loop”; “Core: task, plan, state.” **Concerns:** R8.5.  
    The no-tool-call branch immediately emits a final status. No completion guard checks unresolved local or remote sub-tasks, including children in `INPUT_REQUIRED` or `AUTH_REQUIRED`. **Fix:** define a hooked completion predicate that waits for or explicitly resolves every child before persisting and emitting the parent’s terminal state.

12. **Plans and agent state bypass the replaceable persistence store.**  
    **Section:** “Persistence.” **Concerns:** R9.4, R11.1.  
    The design deliberately stores running task state and plans only in Temporal. That cannot satisfy the explicit requirement to persist plans through the store and allow a hook to replace their persistence target. `StateRecord` appears in the interface but has no corresponding table or write lifecycle. **Fix:** specify store writes and their ordering for plans and agent state, or obtain approval to change those requirements.

13. **Compaction occurs after the call it must protect.**  
    **Sections:** “The core loop”; “Context window manager and compaction.” **Concerns:** R10.4–5, R10.7.  
    The loop invokes the LLM before checking the budget. A large initial message, mailbox update, or loaded skill can therefore exceed the threshold before compaction runs. The trigger and keep-set replacement hooks are also undefined. **Fix:** assemble, measure, and compact before every LLM call; explicitly define the required never-compact set and hooks for all three replaceable policies.

14. **Schema-drift protection is conditional on the server advertising change support.**  
    **Sections:** “Tools and MCP”; “Security design.” **Concerns:** abuse case 8.  
    The concrete mechanism re-lists tools only when the server advertises `listChanged`. A server without that capability can change its schema and still be invoked, contrary to the unconditional abuse-case criterion. **Fix:** define an unconditional pre-invocation schema comparison or a version-pinned registration mechanism, and require re-registration after mismatch.

15. **Help routing has two contradictory default implementations.**  
    **Sections:** “Participants and channels”; “Models.” **Concerns:** R12.4.  
    The channels section defines a rule based on message size and acceptance-criterion dependencies; the models section says `help.decided.in` uses the LLM with structured output. No interface connects those descriptions. **Fix:** define the LLM request/result contract for the default route decision and distinguish validation rules from the replaceable decision body.

16. **The reviewed public interfaces are incomplete and lose required task fields.**  
    **Sections:** “Hooks”; “Plugins”; “Core: task, plan, state”; “Data models”; “Configuration.” **Concerns:** R8.1, R23.1.  
    Hook contexts are deferred with an ellipsis; `HookDef`, several configuration models, intrinsic schemas, `InboundMessage`, `TaskStart`, and `EventPage` are undefined. `TaskExtensionData` omits `name` and `type`, although the core task requires them and A2A supplies neither. `Protocol` is also defined as an enum and subsequently used as the typing-protocol base. **Fix:** finish the interface/schema catalogue before approval, preserve all required task fields, and separate transport and typing protocol names.

17. **No retention policy enforces the personal-data boundary.**  
    **Sections:** “Persistence”; “Observability”; “Security design.” **Concerns:** Security considerations, “Trust boundaries & data.”  
    The requirements explicitly demand retention for the persistence store, Temporal history, and trace exporter. The design names all three but specifies no retention duration, deletion mechanism, or operator configuration. **Fix:** define retention and deletion behavior for each destination, including closed workflows and exported conversation content.

18. **Variable expansion in `command` is left literal instead of rejected.**  
    **Sections:** “Plugins”; “Security design.” **Concerns:** abuse case 3.  
    “Never expanded” does not satisfy “refuse it and record the attempt.” A command containing `${PLUGIN_ROOT}` currently proceeds to process spawning as a literal executable name. **Fix:** validate `command` for forbidden expansion syntax during component loading and reject it with a recorded typed reason.

19. **Vendoring A2UI schemas silently drops the official-SDK requirement.**  
    **Sections:** “Surfaces and renderers”; “Dependencies.” **Concerns:** R22.4.  
    The incompatibility explanation supports avoiding the selected package, but R22.4 explicitly requires the official A2UI SDK and grants loader exceptions only for Skills and Plugins. Schema vendoring is an unapproved exception. **Fix:** select a compatible official integration or obtain and record a requirements amendment.

20. **The design never declares the demo’s token budget.**  
    **Sections:** “Context window manager and compaction”; “Testing strategy.” **Concerns:** Non-functional requirements, “Cost.”  
    A 75% context-window threshold and a cache-prefix minimum do not state the required target token budget per demo turn. **Fix:** declare input/output targets, including tool definitions and loaded skills, and identify the usage evidence that will verify them.
