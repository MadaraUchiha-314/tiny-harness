/**
 * The harness as seen from the browser: the official A2A JavaScript SDK (`@a2a-js/sdk`,
 * protocol 1.0) and nothing else (requirement 20.2). The SDK resolves the agent card,
 * picks the JSON-RPC transport the card advertises, sends `A2A-Version` on every request
 * and parses the event stream; this module only builds messages in the SDK's shapes,
 * adds the perimeter's participant header, and names the harness's media types.
 */
import { ClientFactory, JsonRpcTransportFactory, RestTransportFactory, type Client } from "@a2a-js/sdk/client";
import { Role, TaskState, type Message, type Part, type StreamResponse, type Task } from "@a2a-js/sdk";

export type { Message, Part, StreamResponse, Task };
export { Role, TaskState };

export const A2UI_MEDIA_TYPE = "application/a2ui+json";
export const CHANNEL_MEDIA_TYPE = "application/vnd.tiny-harness.channel+json";
export const TASK_EXT_KEY = "io.github.madarauchiha-314.tiny-harness/task";
export const PARTICIPANT_HEADER = "X-Participant-Id";

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
export class HarnessClient {
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
}
