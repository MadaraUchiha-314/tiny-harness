/**
 * The renderer's view of a task: the A2A event stream folded into conversation items,
 * the task extension (goal, criteria, participants, plan, sub-tasks) read from
 * `Task.metadata`, the status extension's sub-state (issue-25 R5.7), command replies, and
 * the typed placeholder for parts it cannot render (R20.4).
 */
import {
  A2UI_MEDIA_TYPE,
  CHANNEL_MEDIA_TYPE,
  Role,
  STATUS_EXT_KEY,
  TASK_EXT_KEY,
  partData,
  partMediaType,
  partText,
  stateName,
  type JsonObject,
  type Message,
  type Part,
  type StreamResponse,
  type Task,
  type TaskState,
} from "./a2a";
import type { TaskExtensionData } from "./generated/task";
import type { ChannelMessageData } from "./generated/channel";

export type Item =
  | { kind: "text"; role: "user" | "agent"; text: string; key: string }
  | { kind: "status"; state: string; subState: string | null; key: string }
  | { kind: "command"; name: string; text: string; taskRef: string | null; key: string }
  | { kind: "error"; text: string; key: string }
  | { kind: "tool"; text: string; key: string }
  | { kind: "a2ui"; messages: JsonObject[]; key: string }
  | { kind: "help"; text: string; key: string }
  | { kind: "placeholder"; mediaType: string; key: string };

export interface View {
  taskId: string | null;
  contextId: string | null;
  state: string;
  /** Why the task is INPUT_REQUIRED, when the harness says and the value is known. */
  subState: string | null;
  /** The last status message shown, so a task snapshot carrying it does not repeat it. */
  statusMessageId: string | null;
  ext: TaskExtensionData | null;
  items: Item[];
  trace: string[];
}

export const emptyView = (): View => ({
  taskId: null,
  contextId: null,
  state: "—",
  subState: null,
  statusMessageId: null,
  ext: null,
  items: [],
  trace: [],
});

function readExtension(task: Task): TaskExtensionData | null {
  const raw = task.metadata?.[TASK_EXT_KEY];
  if (raw === undefined || raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
  return raw as unknown as TaskExtensionData;
}

/** The sub-states this renderer knows; any other is plain INPUT_REQUIRED (status ext v1). */
export const SUB_STATES: ReadonlySet<string> = new Set(["awaiting-next-message", "awaiting-answer"]);

function readSubState(metadata: { [key: string]: unknown } | undefined): string | null {
  const raw = metadata?.[STATUS_EXT_KEY];
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
  const value = (raw as { [key: string]: unknown })["sub_state"];
  return typeof value === "string" && SUB_STATES.has(value) ? value : null;
}

function metadataString(message: Message, key: string): string | null {
  const value: unknown = message.metadata?.[key];
  return typeof value === "string" && value !== "" ? value : null;
}

function messageItems(message: Message, keyBase: string): Item[] {
  const role = message.role === Role.ROLE_USER ? "user" : "agent";
  const items: Item[] = [];
  // A command's reply (R6.2): the harness marks it with the command's name, and a
  // /sub-task reply with the new task's id.
  const command = role === "agent" ? metadataString(message, "command") : null;
  if (command !== null) {
    const text = message.parts.map(partText).filter((t) => t !== undefined).join("\n");
    const taskRef = metadataString(message, "task_ref");
    return [{ kind: "command", name: command, text, taskRef, key: `${keyBase}:command` }];
  }
  const a2ui: JsonObject[] = [];
  message.parts.forEach((part, index) => {
    const key = `${keyBase}:${index}`;
    const media = partMediaType(part);
    const text = partText(part);
    const data = partData(part);
    if (text !== undefined) {
      items.push({ kind: "text", role, text, key });
    } else if (media === A2UI_MEDIA_TYPE && data !== undefined) {
      a2ui.push(data);
    } else if (media === CHANNEL_MEDIA_TYPE && data !== undefined) {
      const channel = data as unknown as ChannelMessageData;
      if (channel.kind === "help_request") {
        // The help text already arrived as the text part; mark the item as a help request.
        const last = items[items.length - 1];
        if (last && last.kind === "text") {
          items[items.length - 1] = { kind: "help", text: last.text, key: last.key };
        } else {
          items.push({ kind: "help", text: channel.text ?? "", key });
        }
      }
    } else {
      items.push({ kind: "placeholder", mediaType: media, key });
    }
  });
  if (a2ui.length > 0) items.push({ kind: "a2ui", messages: a2ui, key: `${keyBase}:a2ui` });
  return items;
}

/** Folds one stream response into the view; pure, so tests can replay fixtures. */
export function apply(view: View, event: StreamResponse, seq: number): View {
  const next: View = { ...view, items: [...view.items], trace: [...view.trace] };
  const keyBase = `e${seq}`;
  const pushStatus = (state: TaskState | undefined, metadata: { [key: string]: unknown } | undefined) => {
    const name = stateName(state);
    // The sub-state only qualifies INPUT_REQUIRED; leaving it clears the sub-state (R5.7).
    const subState = name === "INPUT_REQUIRED" ? readSubState(metadata) : null;
    if (name !== next.state || subState !== next.subState) {
      next.items.push({ kind: "status", state: name, subState, key: `${keyBase}:status` });
      next.trace.push(subState ? `status · ${name} · ${subState}` : `status · ${name}`);
    }
    next.state = name;
    next.subState = subState;
  };
  const payload = event.payload;
  if (payload === undefined) return next;
  if (payload.$case === "task") {
    const task = payload.value;
    next.taskId = task.id;
    next.contextId = task.contextId;
    next.ext = readExtension(task) ?? next.ext;
    pushStatus(task.status?.state, task.metadata);
    const message = task.status?.message;
    if (message && message.messageId !== next.statusMessageId) {
      next.items.push(...messageItems(message, keyBase));
      next.statusMessageId = message.messageId;
    }
  } else if (payload.$case === "statusUpdate") {
    const update = payload.value;
    next.taskId = update.taskId;
    next.contextId = update.contextId;
    pushStatus(update.status?.state, update.metadata);
    if (update.status?.message) {
      next.items.push(...messageItems(update.status.message, keyBase));
      next.statusMessageId = update.status.message.messageId;
    }
  } else if (payload.$case === "artifactUpdate") {
    const artifact = payload.value.artifact;
    if (artifact === undefined) return next;
    const a2ui: JsonObject[] = [];
    artifact.parts.forEach((part, index) => {
      const media = partMediaType(part);
      const text = partText(part);
      const data = partData(part);
      if (media === A2UI_MEDIA_TYPE && data !== undefined) {
        a2ui.push(data);
      } else if (text !== undefined) {
        next.items.push({ kind: "text", role: "agent", text, key: `${keyBase}:${index}` });
      } else {
        next.items.push({ kind: "placeholder", mediaType: media, key: `${keyBase}:${index}` });
        next.trace.push(`placeholder · ${media}`);
      }
    });
    if (a2ui.length > 0) {
      next.items.push({ kind: "a2ui", messages: a2ui, key: `${keyBase}:a2ui` });
      next.trace.push(`a2ui · ${artifact.name || artifact.artifactId}`);
    }
  } else {
    next.items.push(...messageItems(payload.value, keyBase));
    next.trace.push("message");
  }
  return next;
}

/** Names the task a subscription attaches to (id, context, extension) without folding its
 * status: the replayed log that follows reports the states in order. */
export function attach(view: View, task: Task): View {
  return { ...view, taskId: task.id, contextId: task.contextId, ext: readExtension(task) ?? view.ext };
}

export function replay(events: StreamResponse[]): View {
  return events.reduce((view, event, index) => apply(view, event, index), emptyView());
}
