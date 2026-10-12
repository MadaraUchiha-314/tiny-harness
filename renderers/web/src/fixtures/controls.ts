/**
 * The states of `docs/specs/issue-25/design/web-task-controls.html` without a server: a
 * scripted `HarnessPort` that answers the way the harness does (issue-25). A reply parks
 * the task `INPUT_REQUIRED · awaiting-next-message`; the built-in commands reply on a
 * re-emitted status update; `/sub-task` creates a linked task; the control envelope
 * completes a task, or is refused while a sub-task is open; a terminal task refuses
 * everything. Each task keeps the event log a subscription replays (`?fixture=controls`).
 */
import {
  EVENT_MEDIA_TYPE,
  Role,
  STATUS_EXT_KEY,
  TASK_EXT_KEY,
  TaskState,
  controlMessage,
  partData,
  partText,
  textPart,
  type CommandSpec,
  type HarnessPort,
  type JsonObject,
  type Message,
  type StreamResponse,
  type Task,
} from "../a2a";

export const CONTROLS_ROOT = "7f3a52e0-4b1c-4d6e-9a3f-0c5d8b21c21e";
const CONTEXT_ID = "ctx-7f3a";
const TERMINAL = new Set([
  TaskState.TASK_STATE_COMPLETED,
  TaskState.TASK_STATE_CANCELED,
  TaskState.TASK_STATE_FAILED,
  TaskState.TASK_STATE_REJECTED,
]);

/** The harness's built-in commands, as its card lists them (registration order). */
export const FIXTURE_COMMANDS: CommandSpec[] = [
  { name: "model", description: "Show or choose this task's model", argument_hint: "[<model>]" },
  { name: "effort", description: "Show or set this task's reasoning effort", argument_hint: "[low|medium|high]" },
  { name: "sub-task", description: "Start a linked sub-task", argument_hint: "<description>" },
  { name: "status", description: "Show this task's status", argument_hint: "" },
];

const MODELS = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-luna"];
const EFFORTS = ["low", "medium", "high"];

interface Entry {
  task: Task;
  log: StreamResponse[];
  parent: string | null;
  children: string[];
}

const clone = <T>(value: T): T => structuredClone(value);
const stateName = (state: TaskState): string => `TASK_STATE_${TaskState[state].replace(/^TASK_STATE_/, "")}`;
const short = (state: TaskState): string => TaskState[state].replace(/^TASK_STATE_/, "");

function extension(goal: string, parent: string | null): JsonObject {
  return {
    name: goal.slice(0, 40),
    goal,
    description: "",
    acceptance_criteria: [],
    participants: [
      { id: "tiny-harness", kind: "agent", role: "assignee", display_name: "" },
      { id: "you", kind: "human", role: "reporter", display_name: "" },
    ],
    parent_tasks: parent ? [{ task_id: parent, agent: null }] : [],
    sub_tasks: [],
    plan: null,
    lifecycle: "conversation",
    model: null,
    reasoning_effort: null,
  };
}

export class FixtureClient implements HarnessPort {
  private readonly tasks = new Map<string, Entry>();
  private seq = 0;

  /** `delay` ms passes before an agent reply, so a browser shows the WORKING state. */
  constructor(private readonly delay = 0) {
    const root = this.create(CONTROLS_ROOT, "Summarise the open support tickets and suggest owners.", null);
    root.log.push({
      payload: {
        $case: "message",
        value: this.message(
          CONTROLS_ROOT,
          Role.ROLE_USER,
          "Summarise the three open support tickets and suggest who should take each.",
        ),
      },
    });
    this.emit(root, TaskState.TASK_STATE_WORKING);
    this.emit(
      root,
      TaskState.TASK_STATE_INPUT_REQUIRED,
      "#48213 (damaged blender): billing — refund needs a photo.\n" +
        "#48377 (address change): logistics.\n" +
        "#48402 (login loop): platform on-call.",
    );
  }

  private create(id: string, goal: string, parent: string | null): Entry {
    const task: Task = {
      id,
      contextId: CONTEXT_ID,
      status: { state: TaskState.TASK_STATE_SUBMITTED, message: undefined, timestamp: undefined },
      artifacts: [],
      history: [],
      metadata: { [TASK_EXT_KEY]: extension(goal, parent) },
    };
    const entry: Entry = { task, log: [{ payload: { $case: "task", value: clone(task) } }], parent, children: [] };
    this.tasks.set(id, entry);
    return entry;
  }

  private message(taskId: string, role: Role, text: string, metadata?: { [key: string]: string }): Message {
    return {
      messageId: `fx-${(this.seq += 1)}`,
      contextId: CONTEXT_ID,
      taskId,
      role,
      parts: [textPart(text)],
      metadata,
      extensions: [],
      referenceTaskIds: [],
    };
  }

  /** Move the task to `state` with an optional agent message; a parked task always
   * awaits the next message here, the sub-state the harness writes in both places. */
  private emit(entry: Entry, state: TaskState, text?: string, metadata?: { [key: string]: string }): StreamResponse {
    const message = text === undefined ? undefined : this.message(entry.task.id, Role.ROLE_AGENT, text, metadata);
    const sub = state === TaskState.TASK_STATE_INPUT_REQUIRED ? { [STATUS_EXT_KEY]: { sub_state: "awaiting-next-message" } } : undefined;
    entry.task.status = { state, message, timestamp: undefined };
    const meta: { [key: string]: unknown } = { ...entry.task.metadata };
    delete meta[STATUS_EXT_KEY];
    entry.task.metadata = { ...meta, ...sub };
    const event: StreamResponse = {
      payload: {
        $case: "statusUpdate",
        value: { taskId: entry.task.id, contextId: CONTEXT_ID, status: clone(entry.task.status), metadata: sub },
      },
    };
    entry.log.push(event);
    return clone(event);
  }

  private entry(taskId: string): Entry {
    const entry = this.tasks.get(taskId);
    if (entry === undefined) throw new Error(`task not found: ${taskId}`);
    return entry;
  }

  private refuseTerminal(entry: Entry): void {
    const state = entry.task.status?.state ?? TaskState.TASK_STATE_UNSPECIFIED;
    if (TERMINAL.has(state)) throw new Error(`the task is in a terminal state (${stateName(state)})`);
  }

  private ext(entry: Entry): { [key: string]: unknown } {
    return entry.task.metadata?.[TASK_EXT_KEY] as { [key: string]: unknown };
  }

  private async pause(): Promise<void> {
    if (this.delay > 0) await new Promise((resolve) => setTimeout(resolve, this.delay));
  }

  async *sendMessage(message: Message): AsyncGenerator<StreamResponse> {
    const entry = this.entry(message.taskId);
    this.refuseTerminal(entry);
    const control = message.parts.map(partData).find((d, i) => d !== undefined && message.parts[i]?.mediaType === EVENT_MEDIA_TYPE);
    if (control?.["kind"] === "control" && control["action"] === "complete") {
      const open = entry.children.filter((id) => !TERMINAL.has(this.entry(id).task.status?.state ?? TaskState.TASK_STATE_UNSPECIFIED));
      if (open.length > 0) {
        yield this.emit(entry, TaskState.TASK_STATE_INPUT_REQUIRED, `completion refused: unresolved sub-tasks: ${open.join(", ")}`);
      } else {
        const actor = typeof message.metadata?.["participant_id"] === "string" ? message.metadata["participant_id"] : "you";
        yield this.emit(entry, TaskState.TASK_STATE_COMPLETED, `completed by ${String(actor)}`);
      }
      return;
    }
    const text = message.parts.map(partText).find((t) => t !== undefined) ?? "";
    const match = /^\/([a-z][a-z0-9-]*)(?:\s+([\s\S]*))?$/.exec(text.trim());
    const name = match?.[1];
    const args = (match?.[2] ?? "").trim();
    const reply = (body: string, extra?: { [key: string]: string }) =>
      this.emit(entry, entry.task.status?.state ?? TaskState.TASK_STATE_INPUT_REQUIRED, body, { command: name ?? "", ...extra });
    const ext = this.ext(entry);
    if (name === "model") {
      if (!args) yield reply(`Model: ${String(ext["model"] ?? `${MODELS[0]} (default)`)}\nSelectable: ${MODELS.join(", ")}`);
      else if (!MODELS.includes(args)) yield reply(`refused: not a selectable model. Selectable: ${MODELS.join(", ")}`);
      else {
        ext["model"] = args;
        yield reply(`Model set to ${args}.`);
      }
    } else if (name === "effort") {
      if (!args) yield reply(`Effort: ${String(ext["reasoning_effort"] ?? "provider default")}\nAccepted: ${EFFORTS.join(", ")}`);
      else if (!EFFORTS.includes(args)) yield reply(`refused: not an accepted effort. Accepted: ${EFFORTS.join(", ")}`);
      else {
        ext["reasoning_effort"] = args;
        yield reply(`Effort set to ${args}.`);
      }
    } else if (name === "status") {
      const state = short(entry.task.status?.state ?? TaskState.TASK_STATE_UNSPECIFIED);
      const lines = [`Task ${entry.task.id} · ${String(ext["name"])}`, `State: ${state} · awaiting-next-message`, "Plan: none"];
      if (entry.children.length > 0) {
        lines.push("Sub-tasks:", ...entry.children.map((id) => `- ${id} · ${short(this.entry(id).task.status?.state ?? 0)}`));
      }
      yield reply(lines.join("\n"));
    } else if (name === "sub-task") {
      if (!args) {
        yield reply("Usage: /sub-task <description>");
        return;
      }
      const id = `5b1d${String(entry.children.length + this.tasks.size).padStart(4, "0")}-0c2e-4f1a-8d3b-${entry.task.id.slice(-12)}`;
      const child = this.create(id, args, entry.task.id);
      this.emit(child, TaskState.TASK_STATE_INPUT_REQUIRED);
      entry.children.push(id);
      (ext["sub_tasks"] as JsonObject[]).push({ task_id: id, agent: null });
      // As the harness does: the reply first, then the task listing the new sub-task.
      yield reply(`Starting a sub-task.\nCreated sub-task ${id}.`, { task_ref: id });
      const snapshot: StreamResponse = { payload: { $case: "task", value: clone(entry.task) } };
      entry.log.push(snapshot);
      yield clone(snapshot);
    } else {
      // An ordinary message, an unregistered /x included: a turn, then the task parks.
      yield this.emit(entry, TaskState.TASK_STATE_WORKING);
      await this.pause();
      yield this.emit(entry, TaskState.TASK_STATE_INPUT_REQUIRED, "Noted.");
    }
  }

  async *subscribe(taskId: string): AsyncGenerator<StreamResponse> {
    await Promise.resolve();
    const entry = this.entry(taskId);
    // As the harness does: the task as it is now, then the log after the task's own event.
    yield { payload: { $case: "task", value: clone(entry.task) } };
    for (const event of entry.log.slice(1)) yield clone(event);
  }

  async cancel(taskId: string): Promise<Task> {
    await Promise.resolve();
    const entry = this.entry(taskId);
    this.refuseTerminal(entry);
    this.emit(entry, TaskState.TASK_STATE_CANCELED, "canceled by you");
    return clone(entry.task);
  }

  complete(taskId: string): AsyncGenerator<StreamResponse> {
    return this.sendMessage(controlMessage({ taskId, participant: "you" }));
  }

  async commands(): Promise<CommandSpec[]> {
    await Promise.resolve();
    return clone(FIXTURE_COMMANDS);
  }
}
