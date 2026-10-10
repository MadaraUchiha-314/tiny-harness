/**
 * The renderer's view of a task: the A2A event stream folded into conversation items,
 * the task extension (goal, criteria, participants, plan, sub-tasks) read from
 * `Task.metadata`, and the typed placeholder for parts it cannot render (R20.4).
 */
import {
  A2UI_MEDIA_TYPE,
  CHANNEL_MEDIA_TYPE,
  TASK_EXT_KEY,
  stateName,
  type JsonObject,
  type JsonValue,
  type Message,
  type Part,
  type StreamResponse,
  type Task,
} from "./a2a";
import type { TaskExtensionData } from "./generated/task";
import type { ChannelMessageData } from "./generated/channel";

export type Item =
  | { kind: "text"; role: "user" | "agent"; text: string; key: string }
  | { kind: "status"; state: string; key: string }
  | { kind: "tool"; text: string; key: string }
  | { kind: "a2ui"; messages: JsonObject[]; key: string }
  | { kind: "help"; text: string; key: string }
  | { kind: "placeholder"; mediaType: string; key: string };

export interface View {
  taskId: string | null;
  contextId: string | null;
  state: string;
  ext: TaskExtensionData | null;
  items: Item[];
  trace: string[];
}

export const emptyView = (): View => ({
  taskId: null,
  contextId: null,
  state: "—",
  ext: null,
  items: [],
  trace: [],
});

function partMediaType(part: Part): string {
  if (part.text !== undefined) return "text/plain";
  return part.mediaType ?? "application/octet-stream";
}

function readExtension(task: Task): TaskExtensionData | null {
  const raw = task.metadata?.[TASK_EXT_KEY];
  if (raw === undefined || raw === null || typeof raw !== "object" || Array.isArray(raw)) return null;
  return raw as unknown as TaskExtensionData;
}

function messageItems(message: Message, keyBase: string): Item[] {
  const role = message.role === "ROLE_USER" ? "user" : "agent";
  const items: Item[] = [];
  const a2ui: JsonObject[] = [];
  message.parts.forEach((part, index) => {
    const key = `${keyBase}:${index}`;
    const media = partMediaType(part);
    if (part.text !== undefined) {
      items.push({ kind: "text", role, text: part.text, key });
    } else if (media === A2UI_MEDIA_TYPE && part.data !== undefined && isObject(part.data)) {
      a2ui.push(part.data);
    } else if (media === CHANNEL_MEDIA_TYPE && part.data !== undefined && isObject(part.data)) {
      const data = part.data as unknown as ChannelMessageData;
      if (data.kind === "help_request") {
        // The help text already arrived as the text part; mark the item as a help request.
        const last = items[items.length - 1];
        if (last && last.kind === "text") {
          items[items.length - 1] = { kind: "help", text: last.text, key: last.key };
        } else {
          items.push({ kind: "help", text: data.text ?? "", key });
        }
      }
    } else {
      items.push({ kind: "placeholder", mediaType: media, key });
    }
  });
  if (a2ui.length > 0) items.push({ kind: "a2ui", messages: a2ui, key: `${keyBase}:a2ui` });
  return items;
}

function isObject(value: JsonValue): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Folds one stream response into the view; pure, so tests can replay fixtures. */
export function apply(view: View, event: StreamResponse, seq: number): View {
  const next: View = { ...view, items: [...view.items], trace: [...view.trace] };
  const keyBase = `e${seq}`;
  const pushStatus = (state: string) => {
    const name = stateName(state);
    if (name !== next.state) {
      next.items.push({ kind: "status", state: name, key: `${keyBase}:status` });
      next.trace.push(`status · ${name}`);
    }
    next.state = name;
  };
  if (event.task) {
    next.taskId = event.task.id;
    next.contextId = event.task.contextId;
    next.ext = readExtension(event.task) ?? next.ext;
    pushStatus(event.task.status.state);
    if (event.task.status.message) next.items.push(...messageItems(event.task.status.message, keyBase));
  } else if (event.statusUpdate) {
    next.taskId = event.statusUpdate.taskId;
    next.contextId = event.statusUpdate.contextId;
    pushStatus(event.statusUpdate.status.state);
    if (event.statusUpdate.status.message) {
      next.items.push(...messageItems(event.statusUpdate.status.message, keyBase));
    }
  } else if (event.artifactUpdate) {
    const artifact = event.artifactUpdate.artifact;
    const a2ui: JsonObject[] = [];
    artifact.parts.forEach((part, index) => {
      const media = partMediaType(part);
      if (media === A2UI_MEDIA_TYPE && part.data !== undefined && isObject(part.data)) {
        a2ui.push(part.data);
      } else if (part.text !== undefined) {
        next.items.push({ kind: "text", role: "agent", text: part.text, key: `${keyBase}:${index}` });
      } else {
        next.items.push({ kind: "placeholder", mediaType: media, key: `${keyBase}:${index}` });
        next.trace.push(`placeholder · ${media}`);
      }
    });
    if (a2ui.length > 0) {
      next.items.push({ kind: "a2ui", messages: a2ui, key: `${keyBase}:a2ui` });
      next.trace.push(`a2ui · ${artifact.name ?? artifact.artifactId}`);
    }
  } else if (event.message) {
    next.items.push(...messageItems(event.message, keyBase));
    next.trace.push("message");
  }
  return next;
}

export function replay(events: StreamResponse[]): View {
  return events.reduce((view, event, index) => apply(view, event, index), emptyView());
}
