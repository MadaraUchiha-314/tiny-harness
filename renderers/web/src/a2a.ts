/**
 * The harness as seen from the browser: the official A2A JavaScript SDK (`@a2a-js/sdk`,
 * protocol 1.0) and nothing else (requirement 20.2). The SDK resolves the agent card,
 * picks the JSON-RPC transport the card advertises, sends `A2A-Version` on every request
 * and parses the event stream; this module only builds messages in the SDK's shapes,
 * adds the perimeter's participant header, and names the harness's media types and
 * extensions (issue-25: the control envelope, the status sub-state and the commands).
 */
import { ClientFactory, JsonRpcTransportFactory, RestTransportFactory, type Client } from "@a2a-js/sdk/client";
import { Role, TaskState, type Message, type Part, type StreamResponse, type Task } from "@a2a-js/sdk";
import type { CommandSpec } from "./generated/commands";

export type { CommandSpec, Message, Part, StreamResponse, Task };
export { Role, TaskState };

export const A2UI_MEDIA_TYPE = "application/a2ui+json";
export const CHANNEL_MEDIA_TYPE = "application/vnd.tiny-harness.channel+json";
export const TASK_EXT_KEY = "io.github.madarauchiha-314.tiny-harness/task";
export const PARTICIPANT_HEADER = "X-Participant-Id";
/** The harness's event envelope; `{"kind": "control", "action": "complete"}` completes a task. */
export const EVENT_MEDIA_TYPE = "application/vnd.tiny-harness.event+json";
/** The status extension's key in `Task.metadata` and a status update's metadata. */
export const STATUS_EXT_KEY = "io.github.madarauchiha-314.tiny-harness/status";
export const COMMANDS_EXT_URI = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/commands/v1";
/** The media extension (issue-38): what the agent accepts and produces, and its limits. */
export const MEDIA_EXT_URI = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/media/v1";

/** The media extension's card params (`docs/a2a/ext/media/v1.md`). */
export interface MediaParams {
  input: string[];
  output: string[];
  maxFileBytes: number;
  maxMessageBytes: number;
  maxAudioSeconds: number;
  speechToText: boolean;
  textToSpeech: boolean;
  imageGeneration: boolean;
  mediaPath: string;
}

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

/** `TASK_STATE_WORKING` → `WORKING`; an unknown number is shown as is. */
export function stateName(state: TaskState | undefined): string {
  if (state === undefined) return "—";
  const name = TaskState[state];
  return typeof name === "string" ? name.replace(/^TASK_STATE_/, "") : String(state);
}

export function newId(): string {
  return crypto.randomUUID();
}

export function textPart(text: string): Part {
  return { content: { $case: "text", value: text }, metadata: undefined, filename: "", mediaType: "text/plain" };
}

export function dataPart(data: JsonObject, mediaType: string): Part {
  return { content: { $case: "data", value: data }, metadata: undefined, filename: "", mediaType };
}

export function partText(part: Part): string | undefined {
  return part.content?.$case === "text" ? part.content.value : undefined;
}

export function partData(part: Part): JsonObject | undefined {
  if (part.content?.$case !== "data") return undefined;
  const value: unknown = part.content.value;
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as JsonObject) : undefined;
}

export function partMediaType(part: Part): string {
  if (part.content?.$case === "text") return "text/plain";
  return part.mediaType || "application/octet-stream";
}

export interface SendOptions {
  text?: string;
  parts?: Part[];
  taskId?: string;
  contextId: string;
  participant?: string;
  /** The speaker setting when sent (media extension `speak`): true asks for a spoken reply. */
  speak?: boolean;
}

/** A user message in the SDK's shape; the participant id rides in the metadata (decision-003). */
export function userMessage(options: SendOptions): Message {
  const parts: Part[] = options.parts ?? [];
  if (options.text !== undefined) parts.unshift(textPart(options.text));
  return {
    messageId: newId(),
    contextId: options.contextId,
    taskId: options.taskId ?? "",
    role: Role.ROLE_USER,
    parts,
    metadata: messageMetadata(options),
    extensions: [],
    referenceTaskIds: [],
  };
}

function messageMetadata(options: SendOptions): { [key: string]: unknown } | undefined {
  const metadata: { [key: string]: unknown } = {};
  if (options.participant) metadata["participant_id"] = options.participant;
  if (options.speak !== undefined) metadata["speak"] = options.speak;
  return Object.keys(metadata).length > 0 ? metadata : undefined;
}

/** The message that completes `taskId` (R5.1): one control envelope, sent like any message. */
export function controlMessage(options: { taskId: string; contextId?: string; participant?: string }): Message {
  return userMessage({
    parts: [dataPart({ kind: "control", action: "complete" }, EVENT_MEDIA_TYPE)],
    taskId: options.taskId,
    contextId: options.contextId ?? "",
    ...(options.participant ? { participant: options.participant } : {}),
  });
}

/** The card as far as the commands extension needs it; the SDK's `AgentCard` fits. */
export interface CardWithExtensions {
  capabilities?: { extensions?: Array<{ uri: string; params?: { [key: string]: unknown } | undefined }> } | undefined;
}

/** The registered commands from the card's commands extension, in registration order;
 * none when the card does not declare it (it is optional). Malformed entries are skipped. */
export function commandsOf(card: CardWithExtensions): CommandSpec[] {
  const ext = card.capabilities?.extensions?.find((e) => e.uri === COMMANDS_EXT_URI);
  const raw = ext?.params?.["commands"];
  if (!Array.isArray(raw)) return [];
  const commands: CommandSpec[] = [];
  for (const entry of raw as unknown[]) {
    if (typeof entry !== "object" || entry === null) continue;
    const { name, description, argument_hint: hint, runsOn } = entry as { [key: string]: unknown };
    if (typeof name !== "string" || typeof description !== "string") continue;
    const command: CommandSpec = { name, description, argument_hint: typeof hint === "string" ? hint : "" };
    if (runsOn === "surface" || runsOn === "agent") command.runsOn = runsOn;
    commands.push(command);
  }
  return commands;
}

/** The card's media extension params; null when the card does not declare it (the agent
 * then refuses every file part, so the surface shows no attach, mic or speaker control). */
export function mediaOf(card: CardWithExtensions): MediaParams | null {
  const ext = card.capabilities?.extensions?.find((e) => e.uri === MEDIA_EXT_URI);
  const p = ext?.params;
  if (p === undefined) return null;
  const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
  const number = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
  return {
    input: strings(p["input"]),
    output: strings(p["output"]),
    maxFileBytes: number(p["maxFileBytes"], 0),
    maxMessageBytes: number(p["maxMessageBytes"], 0),
    maxAudioSeconds: number(p["maxAudioSeconds"], 0),
    speechToText: p["speechToText"] === true,
    textToSpeech: p["textToSpeech"] === true,
    imageGeneration: p["imageGeneration"] === true,
    mediaPath: typeof p["mediaPath"] === "string" ? p["mediaPath"] : "/media",
  };
}

/** A task or media id as the server makes them (`_SAFE_ID` in harness/media/store.py). */
const MEDIA_ID = /^[A-Za-z0-9_-]{1,128}$/;

/**
 * `{ taskId, mediaId }` of exactly `<baseUrl><mediaPath>/<taskId>/<mediaId>` on the
 * harness's origin, with no query or fragment and valid ids; null for any other URL.
 */
export function mediaRoute(url: string, baseUrl: string, mediaPath = "/media"): { taskId: string; mediaId: string } | null {
  let found: URL;
  let base: URL;
  try {
    base = new URL(`${baseUrl.replace(/\/$/, "")}/`);
    found = new URL(url, base);
  } catch {
    return null;
  }
  if (found.origin !== base.origin || found.search !== "" || found.hash !== "" || url.includes("#")) return null;
  const root = `${base.pathname.replace(/\/$/, "")}/${mediaPath.replace(/^\/+|\/+$/g, "")}/`;
  if (!found.pathname.startsWith(root)) return null;
  const pieces = found.pathname.slice(root.length).split("/");
  const [taskId, mediaId] = pieces;
  if (pieces.length !== 2 || taskId === undefined || mediaId === undefined) return null;
  if (!MEDIA_ID.test(taskId) || !MEDIA_ID.test(mediaId)) return null;
  return { taskId, mediaId };
}

/** What the renderer needs from a harness; `HarnessClient` is the real one, and the
 * fixtures provide a scripted one for tests and the visual states. */
export interface HarnessPort {
  sendMessage(message: Message): AsyncGenerator<StreamResponse>;
  subscribe(taskId: string, signal?: AbortSignal): AsyncGenerator<StreamResponse>;
  cancel(taskId: string): Promise<Task>;
  complete(taskId: string): AsyncGenerator<StreamResponse>;
  commands(): Promise<CommandSpec[]>;
  /** The card's media extension (issue-38), null without one. */
  media(): Promise<MediaParams | null>;
  /** GET a media URL of this harness with the participant's identity (the media route),
   * only when it is a medium of `taskId`, the task on screen. */
  getMedia(url: string, taskId: string, signal?: AbortSignal): Promise<Response>;
}

/** `fetch` that adds the participant header the perimeter would otherwise set. */
function fetchWithParticipant(participant: string | undefined): typeof fetch {
  if (!participant) return fetch;
  return (input, init) => {
    const headers = new Headers(init?.headers);
    headers.set(PARTICIPANT_HEADER, participant);
    return fetch(input, { ...init, headers });
  };
}

/** The SDK client for one server, built from its agent card on first use. */
export class HarnessClient implements HarnessPort {
  private client: Promise<Client> | null = null;
  private readonly fetchImpl: typeof fetch;

  constructor(
    private readonly baseUrl: string,
    private readonly participant?: string,
  ) {
    this.fetchImpl = fetchWithParticipant(participant);
  }

  private connect(): Promise<Client> {
    if (this.client === null) {
      const fetchImpl = this.fetchImpl;
      const factory = new ClientFactory({
        transports: [new JsonRpcTransportFactory({ fetchImpl }), new RestTransportFactory({ fetchImpl })],
        preferredTransports: ["JSONRPC", "HTTP+JSON"],
      });
      this.client = factory.createFromUrl(this.baseUrl);
    }
    return this.client;
  }

  async *sendMessage(message: Message): AsyncGenerator<StreamResponse> {
    const client = await this.connect();
    yield* client.sendMessageStream({ tenant: "", message, configuration: undefined, metadata: undefined });
  }

  /** The task's event log from its start, then live updates, until the signal aborts. */
  async *subscribe(taskId: string, signal?: AbortSignal): AsyncGenerator<StreamResponse> {
    const client = await this.connect();
    yield* client.resubscribeTask({ tenant: "", id: taskId }, signal ? { signal } : {});
  }

  async cancel(taskId: string): Promise<Task> {
    const client = await this.connect();
    return client.cancelTask({ tenant: "", id: taskId, metadata: undefined });
  }

  /** Complete the task (R5.1) the way any A2A client can: `SendMessage` with the control envelope. */
  complete(taskId: string): AsyncGenerator<StreamResponse> {
    return this.sendMessage(controlMessage({ taskId, ...(this.participant ? { participant: this.participant } : {}) }));
  }

  /** The commands the card advertises, for the composer's `/` completions (R6.7). */
  async commands(): Promise<CommandSpec[]> {
    const client = await this.connect();
    return commandsOf(await client.getAgentCard());
  }

  async media(): Promise<MediaParams | null> {
    const client = await this.connect();
    return mediaOf(await client.getAgentCard());
  }

  /** Only this harness's exact media route, for the task on screen, gets the
   * participant's identity (critic 8): any other URL is refused, not fetched (the server
   * never sends one). */
  async getMedia(url: string, taskId: string, signal?: AbortSignal): Promise<Response> {
    const media = (await this.media())?.mediaPath ?? "/media";
    const route = mediaRoute(url, this.baseUrl, media);
    if (route === null || !taskId || route.taskId !== taskId) {
      throw new Error(`not a media URL of task ${taskId || "(none)"}: ${url}`);
    }
    return this.fetchImpl(new URL(url, `${this.baseUrl}/`).href, signal ? { signal } : {});
  }
}
