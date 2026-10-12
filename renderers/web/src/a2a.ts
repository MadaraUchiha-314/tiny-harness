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
    metadata: options.participant ? { participant_id: options.participant } : undefined,
    extensions: [],
    referenceTaskIds: [],
  };
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
    const { name, description, argument_hint: hint } = entry as { [key: string]: unknown };
    if (typeof name !== "string" || typeof description !== "string") continue;
    commands.push({ name, description, argument_hint: typeof hint === "string" ? hint : "" });
  }
  return commands;
}

/** What the renderer needs from a harness; `HarnessClient` is the real one, and the
 * fixtures provide a scripted one for tests and the visual states. */
export interface HarnessPort {
  sendMessage(message: Message): AsyncGenerator<StreamResponse>;
  subscribe(taskId: string, signal?: AbortSignal): AsyncGenerator<StreamResponse>;
  cancel(taskId: string): Promise<Task>;
  complete(taskId: string): AsyncGenerator<StreamResponse>;
  commands(): Promise<CommandSpec[]>;
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

  constructor(
    private readonly baseUrl: string,
    private readonly participant?: string,
  ) {}

  private connect(): Promise<Client> {
    if (this.client === null) {
      const fetchImpl = fetchWithParticipant(this.participant);
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
}
