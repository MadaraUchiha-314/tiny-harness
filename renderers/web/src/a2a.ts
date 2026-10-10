/**
 * The A2A 1.0 HTTP+JSON binding (requirement 20.2): `POST /message:stream` and
 * `GET /tasks/{id}:subscribe` as server-sent events, every request with
 * `A2A-Version: 1.0`. Types mirror the protobuf JSON of a2a.v1.
 */

export const A2A_VERSION = "1.0";
export const A2UI_MEDIA_TYPE = "application/a2ui+json";
export const CHANNEL_MEDIA_TYPE = "application/vnd.tiny-harness.channel+json";
export const TASK_EXT_KEY = "io.github.madarauchiha-314.tiny-harness/task";

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface Part {
  text?: string;
  data?: JsonValue;
  mediaType?: string;
  filename?: string;
}

export interface Message {
  messageId: string;
  contextId?: string;
  taskId?: string;
  role: "ROLE_USER" | "ROLE_AGENT";
  parts: Part[];
  metadata?: JsonObject;
}

export interface TaskStatus {
  state: string;
  message?: Message;
  timestamp?: string;
}

export interface Task {
  id: string;
  contextId: string;
  status: TaskStatus;
  artifacts?: Artifact[];
  metadata?: JsonObject;
}

export interface Artifact {
  artifactId: string;
  name?: string;
  parts: Part[];
}

export interface TaskStatusUpdateEvent {
  taskId: string;
  contextId: string;
  status: TaskStatus;
}

export interface TaskArtifactUpdateEvent {
  taskId: string;
  contextId: string;
  artifact: Artifact;
  lastChunk?: boolean;
}

export interface StreamResponse {
  task?: Task;
  message?: Message;
  statusUpdate?: TaskStatusUpdateEvent;
  artifactUpdate?: TaskArtifactUpdateEvent;
}

export function stateName(state: string): string {
  return state.replace(/^TASK_STATE_/, "");
}

export function newId(): string {
  return crypto.randomUUID();
}

export interface SendOptions {
  text?: string;
  parts?: Part[];
  taskId?: string;
  contextId: string;
  participant?: string;
}

export function userMessage(options: SendOptions): Message {
  const parts: Part[] = options.parts ?? [];
  if (options.text !== undefined) parts.unshift({ text: options.text });
  const message: Message = {
    messageId: newId(),
    contextId: options.contextId,
    role: "ROLE_USER",
    parts,
  };
  if (options.taskId) message.taskId = options.taskId;
  if (options.participant) message.metadata = { participant_id: options.participant };
  return message;
}

/**
 * Parses an SSE body into the JSON of each `data:` event. Frames end with a blank line;
 * the SSE specification allows CRLF, LF or CR line endings and the a2a-sdk server sends
 * CRLF, so line endings are normalised before the frames are split.
 */
export async function* sseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamResponse> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let carry = ""; // a trailing CR held back until the next chunk says whether LF follows
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    let chunk = carry + decoder.decode(value, { stream: true });
    carry = chunk.endsWith("\r") ? "\r" : "";
    if (carry) chunk = chunk.slice(0, -1);
    buffer += chunk.replace(/\r\n|\r/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (data) yield JSON.parse(data) as StreamResponse;
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export class A2AClient {
  constructor(
    private readonly baseUrl: string,
    private readonly participant?: string,
  ) {}

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {
      "A2A-Version": A2A_VERSION,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    if (this.participant) headers["X-Participant-Id"] = this.participant;
    return headers;
  }

  private async *stream(response: Response): AsyncGenerator<StreamResponse> {
    if (!response.ok || response.body === null) {
      const text = await response.text().catch(() => "");
      throw new Error(`A2A request failed: ${response.status} ${text}`.trim());
    }
    yield* sseEvents(response.body);
  }

  async *sendMessage(message: Message): AsyncGenerator<StreamResponse> {
    const response = await fetch(`${this.baseUrl}/message:stream`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ message }),
    });
    yield* this.stream(response);
  }

  async *subscribe(taskId: string): AsyncGenerator<StreamResponse> {
    const response = await fetch(`${this.baseUrl}/tasks/${encodeURIComponent(taskId)}:subscribe`, {
      headers: this.headers(),
    });
    yield* this.stream(response);
  }

  async cancel(taskId: string): Promise<Task> {
    const response = await fetch(`${this.baseUrl}/tasks/${encodeURIComponent(taskId)}:cancel`, {
      method: "POST",
      headers: this.headers(),
      body: "{}",
    });
    if (!response.ok) throw new Error(`cancel failed: ${response.status}`);
    return (await response.json()) as Task;
  }
}
