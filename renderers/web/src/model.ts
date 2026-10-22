/**
 * The renderer's view of a task: the A2A event stream folded into conversation items,
 * the task extension (goal, criteria, participants, plan, sub-tasks) read from
 * `Task.metadata`, the status extension's sub-state (issue-25 R5.7), command replies, and
 * the typed placeholder for parts it cannot render (R20.4). Issue-38 adds media: a `url`
 * file part of an accepted type becomes a media item, the user's message echo
 * (`message:<id>`) binds or shows the user's files, a `transcript:<mediaId>` artifact fills
 * in its voice turn, `image:<mediaId>` is the agent's image and `speech:<mediaId>` its
 * spoken reply, placed under the reply's text.
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
import { mediaKind, type MediaKind } from "./media";
import type { ChannelMessageData } from "./generated/channel";

/** An image or audio file in a turn; `url` is the media route's URL, or the `local:` key of
 * a file this page is sending until the server's echo names its stored URL. */
export interface MediaItemData {
  kind: "media";
  role: "user" | "agent";
  media: MediaKind;
  url: string;
  /** The file name, or for the agent's image its alt text. */
  name: string;
  mediaType: string;
  mediaId: string | null;
  /** The user message it came in, so the echo can bind it and a refusal remove it. */
  messageId: string | null;
  key: string;
  transcript?: string;
  voice?: boolean;
  durationMs?: number;
  size?: number;
  width?: number;
  height?: number;
}

/** A spoken reply: PCM streamed from `url` while the server writes it. */
export interface SpeechItemData {
  kind: "speech";
  url: string;
  mediaId: string;
  state: "streaming" | "done" | "failed";
  key: string;
}

export type Item =
  | { kind: "text"; role: "user" | "agent"; text: string; key: string; messageId?: string }
  | MediaItemData
  | SpeechItemData
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
  /** Transcripts by media id, for a voice item shown after its transcript arrived. */
  transcripts: { [mediaId: string]: string };
  /** The key of a spoken reply still waiting for its reply's text. */
  unplacedSpeech: string | null;
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
  transcripts: {},
  unplacedSpeech: null,
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
    const file = mediaItem(part, role, key, role === "user" ? message.messageId : null);
    if (text !== undefined) {
      items.push(role === "user" ? { kind: "text", role, text, key, messageId: message.messageId } : { kind: "text", role, text, key });
    } else if (file !== null) {
      items.push(file);
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

const SPEECH_UNAVAILABLE = "speech unavailable";
const MESSAGE_ARTIFACT = "message:";
const TRANSCRIPT_ARTIFACT = "transcript:";
const IMAGE_ARTIFACT = "image:";
const SPEECH_ARTIFACT = "speech:";

/** The media extension's flat part metadata, as far as the renderer shows it. */
function partMeta(part: Part): Partial<Pick<MediaItemData, "voice" | "durationMs" | "size" | "width" | "height">> & {
  mediaId?: string;
} {
  const m: { [key: string]: unknown } = part.metadata ?? {};
  const out: ReturnType<typeof partMeta> = {};
  if (typeof m["mediaId"] === "string") out.mediaId = m["mediaId"];
  if (m["voice"] === true) out.voice = true;
  for (const key of ["durationMs", "size", "width", "height"] as const) {
    const value = m[key];
    if (typeof value === "number" && Number.isFinite(value)) out[key] = value;
  }
  return out;
}

/** A `url` file part of an accepted image or audio type (not the speech type) as a media
 * item; anything else (an SVG, HTML, a raw part from elsewhere) is not one. */
function mediaItem(part: Part, role: "user" | "agent", key: string, messageId: string | null): MediaItemData | null {
  if (part.content?.$case !== "url") return null;
  const kind = mediaKind(part.mediaType);
  if (kind === null || part.mediaType.startsWith("audio/L16")) return null;
  const { mediaId, ...meta } = partMeta(part);
  return {
    kind: "media",
    role,
    media: kind,
    url: part.content.value,
    name: part.filename || (kind === "image" ? "image" : "audio"),
    mediaType: part.mediaType,
    mediaId: mediaId ?? null,
    messageId,
    key,
    ...meta,
  };
}

function withTranscript(item: MediaItemData, transcripts: { [mediaId: string]: string }): MediaItemData {
  const text = item.mediaId !== null ? transcripts[item.mediaId] : undefined;
  return text === undefined ? item : { ...item, transcript: text };
}

/** The user's message as stored: bind the files this page already shows (same message
 * id) to their stored URLs, else show the sender's files and text. */
function foldEcho(next: View, parts: Part[], metadata: { [key: string]: unknown } | undefined, artifactId: string, keyBase: string): void {
  const raw = metadata?.["message_id"];
  const messageId = typeof raw === "string" && raw !== "" ? raw : artifactId.slice(MESSAGE_ARTIFACT.length);
  const files = parts.flatMap((part, index) => {
    const item = mediaItem(part, "user", `${keyBase}:${index}`, messageId);
    return item === null ? [] : [withTranscript(item, next.transcripts)];
  });
  const shown = next.items.flatMap((item, at) => (item.kind === "media" && item.messageId === messageId ? [at] : []));
  if (shown.length > 0) {
    shown.forEach((at, n) => {
      const stored = files[n];
      const item = next.items[at] as MediaItemData;
      if (stored === undefined) return;
      const { key: _key, name: _name, ...rest } = stored;
      next.items[at] = withTranscript({ ...item, ...rest, key: item.key, name: item.name }, next.transcripts);
    });
    next.trace.push("message · media stored");
    return;
  }
  next.items.push(...files);
  parts.forEach((part, index) => {
    const text = partText(part);
    if (text !== undefined) next.items.push({ kind: "text", role: "user", text, key: `${keyBase}:t${index}`, messageId });
  });
  next.trace.push("message · media");
}

/** A spoken reply arrives before its reply's text: it moves under that text. */
function placeSpeech(next: View, added: Item[]): void {
  const lastText = [...added].reverse().find((i) => i.kind === "text" && i.role === "agent");
  if (lastText === undefined) return;
  if (lastText.kind === "text" && lastText.text.trim() === SPEECH_UNAVAILABLE) {
    let at = next.items.length - 1;
    while (at >= 0 && next.items[at]?.kind !== "speech") at -= 1;
    const speech = next.items[at];
    if (speech?.kind === "speech") next.items[at] = { ...speech, state: "failed" };
    return;
  }
  if (next.unplacedSpeech === null) return;
  const from = next.items.findIndex((i) => i.key === next.unplacedSpeech);
  next.unplacedSpeech = null;
  if (from < 0) return;
  const [speech] = next.items.splice(from, 1);
  const to = next.items.findIndex((i) => i.key === lastText.key);
  if (speech !== undefined) next.items.splice(to + 1, 0, speech);
}

/** The files the page showed from its own copy (a `local:` key) that `after` binds to
 * their stored URLs: the page aliases each so it never downloads them again. */
export function rebound(before: View, after: View): Array<{ src: string; key: string }> {
  const local = new Map<string, string>();
  for (const item of before.items) if (item.kind === "media" && item.url.startsWith("local:")) local.set(item.key, item.url);
  if (local.size === 0) return [];
  return after.items.flatMap((item) => {
    const key = item.kind === "media" ? local.get(item.key) : undefined;
    return item.kind === "media" && key !== undefined && item.url !== key ? [{ src: item.url, key }] : [];
  });
}

/** The view without the user's items of `messageId`: the server refused that message. */
export function withoutMessage(view: View, messageId: string): View {
  return {
    ...view,
    items: view.items.filter((i) => !((i.kind === "media" || i.kind === "text") && i.messageId === messageId)),
  };
}

/** Folds one stream response into the view; pure, so tests can replay fixtures. */
export function apply(view: View, event: StreamResponse, seq: number): View {
  const next: View = { ...view, items: [...view.items], trace: [...view.trace], transcripts: { ...view.transcripts } };
  const pushMessage = (message: Message) => {
    const added = messageItems(message, keyBase);
    next.items.push(...added);
    placeSpeech(next, added);
  };
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
      pushMessage(message);
      next.statusMessageId = message.messageId;
    }
  } else if (payload.$case === "statusUpdate") {
    const update = payload.value;
    next.taskId = update.taskId;
    next.contextId = update.contextId;
    pushStatus(update.status?.state, update.metadata);
    if (update.status?.message) {
      pushMessage(update.status.message);
      next.statusMessageId = update.status.message.messageId;
    }
  } else if (payload.$case === "artifactUpdate") {
    const artifact = payload.value.artifact;
    if (artifact === undefined) return next;
    const id = artifact.artifactId;
    if (id.startsWith(MESSAGE_ARTIFACT)) {
      foldEcho(next, artifact.parts, artifact.metadata, id, keyBase);
      return next;
    }
    if (id.startsWith(TRANSCRIPT_ARTIFACT)) {
      const mediaId = id.slice(TRANSCRIPT_ARTIFACT.length);
      const text = artifact.parts.map(partText).filter((t) => t !== undefined).join("\n");
      next.transcripts[mediaId] = text;
      next.items = next.items.map((i) => (i.kind === "media" && i.mediaId === mediaId ? { ...i, transcript: text } : i));
      next.trace.push("transcript");
      return next;
    }
    if (id.startsWith(SPEECH_ARTIFACT)) {
      const part = artifact.parts.find((p) => p.content?.$case === "url");
      if (part?.content?.$case === "url") {
        const key = `${keyBase}:speech`;
        next.items.push({ kind: "speech", url: part.content.value, mediaId: id.slice(SPEECH_ARTIFACT.length), state: "streaming", key });
        next.unplacedSpeech = key;
        next.trace.push("speech");
      }
      return next;
    }
    const a2ui: JsonObject[] = [];
    artifact.parts.forEach((part, index) => {
      const media = partMediaType(part);
      const text = partText(part);
      const data = partData(part);
      const file = mediaItem(part, "agent", `${keyBase}:${index}`, null);
      if (media === A2UI_MEDIA_TYPE && data !== undefined) {
        a2ui.push(data);
      } else if (text !== undefined) {
        next.items.push({ kind: "text", role: "agent", text, key: `${keyBase}:${index}` });
      } else if (file !== null) {
        // The agent's image is named by its alt text (the artifact's name).
        next.items.push(id.startsWith(IMAGE_ARTIFACT) && artifact.name ? { ...file, name: artifact.name } : file);
        next.trace.push(`${file.media} · ${file.mediaType}`);
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
    pushMessage(payload.value);
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
