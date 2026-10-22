/**
 * The states of `docs/specs/issue-38/design/web-multimodal.html` without a server
 * (`?fixture=media`): a scripted `HarnessPort` whose card declares the media extension and
 * the `/attach` surface command, and which answers the way the harness does — it checks
 * each file part (type and signature; a refusal is `InvalidParams` with `reason` and
 * `part`, and nothing is stored), echoes the stored message as `message:<id>`, transcribes
 * a voice part, speaks the reply when the message asks (`speak`) and serves its media
 * route from memory. Images are drawn here as real PNGs, audio is real WAV and PCM.
 * `?speech=broken` makes every spoken reply's stream break (the "interrupted" state).
 */
import {
  Role,
  STATUS_EXT_KEY,
  TASK_EXT_KEY,
  TaskState,
  textPart,
  type CommandSpec,
  type HarnessPort,
  type MediaParams,
  type Message,
  type Part,
  type StreamResponse,
  type Task,
} from "../a2a";
import { PCM_MEDIA_TYPE, baseType } from "../media";
import { FIXTURE_COMMANDS } from "./controls";

export const MEDIA_ROOT = "9c41d2e0-7a1b-4c3d-8e5f-60a7b8c9e07b";
const CONTEXT_ID = "ctx-9c41";
const BASE = "http://fixture.invalid";

export const FIXTURE_MEDIA: MediaParams = {
  input: ["image/png", "image/jpeg", "image/webp", "image/gif", "audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/webm"],
  output: ["image/png", PCM_MEDIA_TYPE],
  maxFileBytes: 20 * 1024 * 1024,
  maxMessageBytes: 25 * 1024 * 1024,
  maxAudioSeconds: 120,
  speechToText: true,
  textToSpeech: true,
  imageGeneration: true,
  mediaPath: "/media",
};

export const MEDIA_COMMANDS: CommandSpec[] = [
  ...FIXTURE_COMMANDS,
  { name: "attach", description: "Attach a local image or audio file to your next message", argument_hint: "<path>", runsOn: "surface" },
];

// --- real bytes -----------------------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of bytes) c = (CRC_TABLE[(c ^ b) & 0xff] ?? 0) ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function concat(chunks: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

const be32 = (n: number) => new Uint8Array([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]);

/** An RGB image as a PNG (zlib with stored blocks: no compressor needed). */
function png(width: number, height: number, pixel: (x: number, y: number) => [number, number, number]): Uint8Array {
  const raw = new Uint8Array((width * 3 + 1) * height);
  for (let y = 0, at = 0; y < height; y += 1) {
    raw[at++] = 0;
    for (let x = 0; x < width; x += 1) {
      const [r, g, b] = pixel(x, y);
      raw[at++] = r;
      raw[at++] = g;
      raw[at++] = b;
    }
  }
  const blocks: Uint8Array[] = [new Uint8Array([0x78, 0x01])];
  for (let at = 0; at < raw.length; at += 65535) {
    const piece = raw.subarray(at, Math.min(raw.length, at + 65535));
    const last = at + 65535 >= raw.length ? 1 : 0;
    blocks.push(new Uint8Array([last, piece.length & 255, piece.length >>> 8, ~piece.length & 255, (~piece.length >>> 8) & 255]), piece);
  }
  let a = 1;
  let b = 0;
  for (const byte of raw) {
    a = (a + byte) % 65521;
    b = (b + a) % 65521;
  }
  blocks.push(be32(((b << 16) | a) >>> 0));
  const chunk = (type: string, data: Uint8Array) => {
    const body = concat([new TextEncoder().encode(type), data]);
    return concat([be32(data.length), body, be32(crc32(body))]);
  };
  const header = concat([be32(width), be32(height), new Uint8Array([8, 2, 0, 0, 0])]);
  return concat([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header), chunk("IDAT", concat(blocks)), chunk("IEND", new Uint8Array())]);
}

const hex = (h: string): [number, number, number] => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

/** The prototype's room: a wall, a floor, a sofa and a framed picture (and, generated, a
 * green sofa on a rust rug). */
function room(width: number, height: number, generated: boolean): Uint8Array {
  const wall = hex("#e9e2d4");
  const floor = hex("#c9b79c");
  const sofa = hex(generated ? "#3f8a4e" : "#7d8f86");
  const frame = hex("#7d8f86");
  const rug = hex("#b5532f");
  return png(width, height, (x, y) => {
    const u = x / width;
    const v = y / height;
    const inFrame = u >= 0.7 && u <= 0.88 && v >= 0.16 && v <= 0.46;
    const frameEdge = inFrame && (u < 0.71 || u > 0.87 || v < 0.175 || v > 0.445);
    if (frameEdge) return frame;
    if (u >= 0.14 && u <= 0.7 && v >= 0.56 && v <= 0.82) return sofa;
    if (generated && u >= 0.08 && u <= 0.8 && v > 0.82 && v <= 0.95) return rug;
    return v < 0.55 ? wall : floor;
  });
}

/** Mono 16-bit PCM of a soft tone (a voice stand-in), `seconds` long. */
function tone(sampleRate: number, seconds: number, from = 0): Int16Array {
  const samples = new Int16Array(Math.round(sampleRate * seconds));
  for (let i = 0; i < samples.length; i += 1) {
    const t = (from + i) / sampleRate;
    samples[i] = Math.round(Math.sin(2 * Math.PI * 220 * t) * 2000 * (0.6 + 0.4 * Math.sin(2 * Math.PI * 3 * t)));
  }
  return samples;
}

function wav(seconds: number): Uint8Array {
  const rate = 16_000;
  const pcm = new Uint8Array(tone(rate, seconds).buffer);
  const header = new DataView(new ArrayBuffer(44));
  const ascii = (at: number, s: string) => [...s].forEach((c, i) => header.setUint8(at + i, c.charCodeAt(0)));
  ascii(0, "RIFF");
  header.setUint32(4, 36 + pcm.length, true);
  ascii(8, "WAVEfmt ");
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true);
  header.setUint16(22, 1, true);
  header.setUint32(24, rate, true);
  header.setUint32(28, rate * 2, true);
  header.setUint16(32, 2, true);
  header.setUint16(34, 16, true);
  ascii(36, "data");
  header.setUint32(40, pcm.length, true);
  return concat([new Uint8Array(header.buffer), pcm]);
}

/** The leading bytes each accepted type must start with (the server's sniff, in short). */
const SIGNATURES: { [type: string]: (b: Uint8Array) => boolean } = {
  "image/png": (b) => b[0] === 137 && b[1] === 80 && b[2] === 78 && b[3] === 71,
  "image/jpeg": (b) => b[0] === 0xff && b[1] === 0xd8,
  "image/gif": (b) => b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46,
  "image/webp": (b) => b[0] === 0x52 && b[8] === 0x57,
  "audio/wav": (b) => b[0] === 0x52 && b[1] === 0x49 && b[8] === 0x57,
  "audio/webm": (b) => b[0] === 0x1a && b[1] === 0x45 && b[2] === 0xdf && b[3] === 0xa3,
  "audio/ogg": (b) => b[0] === 0x4f && b[1] === 0x67,
  "audio/mp4": (b) => b[4] === 0x66 && b[5] === 0x74,
  "audio/mpeg": (b) => (b[0] === 0x49 && b[1] === 0x44) || b[0] === 0xff,
};

/** The A2A `InvalidParams` refusal the harness answers a bad file with. */
export class FixtureRefusal extends Error {
  readonly code = -32602;
  constructor(
    message: string,
    readonly data: { reason: string; part: number; limit?: number },
  ) {
    super(message);
    this.name = "RequestMalformedError";
  }
}

interface Stored {
  bytes: Uint8Array;
  mediaType: string;
}

const clone = <T>(value: T): T => structuredClone(value);

export class MediaFixtureClient implements HarnessPort {
  private readonly store = new Map<string, Stored>();
  private readonly speech = new Set<string>();
  private readonly log: StreamResponse[] = [];
  private task: Task;
  private seq = 0;

  /** `delay` ms passes before a reply; `broken` speech breaks off after a few chunks. */
  constructor(private readonly options: { delay?: number; speech?: "ok" | "broken" } = {}) {
    this.task = {
      id: MEDIA_ROOT,
      contextId: CONTEXT_ID,
      status: { state: TaskState.TASK_STATE_SUBMITTED, message: undefined, timestamp: undefined },
      artifacts: [],
      history: [],
      metadata: {
        [TASK_EXT_KEY]: {
          name: "Make the living room feel warmer",
          goal: "Suggest changes that make the living room feel warmer, and show one.",
          description: "",
          acceptance_criteria: [],
          participants: [
            { id: "tiny-harness", kind: "agent", role: "assignee", display_name: "" },
            { id: "you", kind: "human", role: "reporter", display_name: "" },
          ],
          parent_tasks: [],
          sub_tasks: [],
          plan: null,
          lifecycle: "conversation",
          model: null,
          reasoning_effort: null,
        },
      },
    };
    this.log.push({ payload: { $case: "task", value: clone(this.task) } });
    this.seed();
  }

  private id(prefix: string): string {
    this.seq += 1;
    return `${prefix}${String(this.seq).padStart(4, "0")}Qm3xk2`;
  }

  private url(mediaId: string): string {
    return `${BASE}/media/${MEDIA_ROOT}/${mediaId}`;
  }

  private put(bytes: Uint8Array, mediaType: string): string {
    const id = this.id("m");
    this.store.set(id, { bytes, mediaType });
    return id;
  }

  private urlPart(mediaId: string, mediaType: string, filename: string, metadata: { [key: string]: unknown }): Part {
    return { content: { $case: "url", value: this.url(mediaId) }, metadata: { mediaId, ...metadata }, filename, mediaType };
  }

  private record(event: StreamResponse): StreamResponse {
    this.log.push(event);
    return clone(event);
  }

  private status(state: TaskState, text?: string): StreamResponse {
    const message: Message | undefined =
      text === undefined
        ? undefined
        : {
            messageId: this.id("fx-"),
            contextId: CONTEXT_ID,
            taskId: MEDIA_ROOT,
            role: Role.ROLE_AGENT,
            parts: [textPart(text)],
            metadata: undefined,
            extensions: [],
            referenceTaskIds: [],
          };
    const sub = state === TaskState.TASK_STATE_INPUT_REQUIRED ? { [STATUS_EXT_KEY]: { sub_state: "awaiting-next-message" } } : undefined;
    this.task.status = { state, message, timestamp: undefined };
    this.task.metadata = { ...this.task.metadata, ...sub };
    return this.record({
      payload: { $case: "statusUpdate", value: { taskId: MEDIA_ROOT, contextId: CONTEXT_ID, status: clone(this.task.status), metadata: sub } },
    });
  }

  private artifact(artifactId: string, name: string, parts: Part[], metadata: { [key: string]: unknown }): StreamResponse {
    return this.record({
      payload: {
        $case: "artifactUpdate",
        value: {
          taskId: MEDIA_ROOT,
          contextId: CONTEXT_ID,
          artifact: { artifactId, name, description: "", parts, metadata, extensions: [] },
          append: false,
          lastChunk: true,
          metadata: undefined,
        },
      },
    });
  }

  private echo(messageId: string, parts: Part[]): StreamResponse {
    return this.artifact(`message:${messageId}`, "user message", parts, { role: "user", participant_id: "you", message_id: messageId });
  }

  private speak(): StreamResponse {
    const id = this.id("s");
    this.speech.add(id);
    return this.artifact(`speech:${id}`, "speech", [this.urlPart(id, PCM_MEDIA_TYPE, "", {})], { mediaId: id });
  }

  private seed(): void {
    const photo = room(480, 360, false);
    const photoId = this.put(photo, "image/png");
    this.echo("fx-u1", [
      this.urlPart(photoId, "image/png", "living-room.png", { size: photo.length, width: 480, height: 360 }),
      textPart("What would make this room feel warmer?"),
    ]);
    this.status(TaskState.TASK_STATE_WORKING);
    this.status(
      TaskState.TASK_STATE_INPUT_REQUIRED,
      "The grey sofa and beige wall are cool and flat. Try a warm-toned throw, a rug with rust or ochre, and a lamp at 2700 K beside the sofa.",
    );
    const voice = wav(4);
    const voiceId = this.put(voice, "audio/wav");
    this.echo("fx-u2", [this.urlPart(voiceId, "audio/wav", "voice.wav", { size: voice.length, durationMs: 4000, voice: true })]);
    this.status(TaskState.TASK_STATE_WORKING);
    this.artifact(`transcript:${voiceId}`, "transcript", [textPart("Would a rug work better than a throw on the sofa in the first photo?")], {
      mediaId: voiceId,
    });
    this.speak();
    this.status(
      TaskState.TASK_STATE_INPUT_REQUIRED,
      "Yes — a 160 × 230 cm rug in rust under the front legs of the sofa warms the whole floor; a throw only changes the sofa.",
    );
    this.status(TaskState.TASK_STATE_WORKING);
    const mock = room(480, 360, true);
    const mockId = this.put(mock, "image/png");
    this.status(TaskState.TASK_STATE_INPUT_REQUIRED, "Here is a mock-up with a green sofa and a rust rug:");
    this.artifact(
      `image:${mockId}`,
      "Generated: the same room with a green sofa and a rust rug",
      [this.urlPart(mockId, "image/png", "mock-up.png", { size: mock.length, width: 480, height: 360 })],
      { mediaId: mockId },
    );
  }

  private async pause(): Promise<void> {
    if (this.options.delay) await new Promise((resolve) => setTimeout(resolve, this.options.delay));
  }

  async *sendMessage(message: Message): AsyncGenerator<StreamResponse> {
    await Promise.resolve();
    // Every file part is checked before anything is stored (the harness's intake).
    const stored: Part[] = [];
    let voice = false;
    message.parts.forEach((part, index) => {
      if (part.content?.$case === "text") {
        stored.push(textPart(part.content.value));
        return;
      }
      if (part.content?.$case !== "raw") return;
      const bytes = new Uint8Array(part.content.value);
      const type = baseType(part.mediaType);
      const check = SIGNATURES[type];
      if (!FIXTURE_MEDIA.input.includes(type) || check === undefined) {
        throw new FixtureRefusal("type not accepted", { reason: "type_not_accepted", part: index });
      }
      if (!check(bytes)) throw new FixtureRefusal("type mismatch", { reason: "type_mismatch", part: index });
      const id = this.put(bytes, type);
      const meta: { [key: string]: unknown } = { ...(part.metadata ?? {}), size: bytes.length };
      if (meta["voice"] === true) voice = true;
      stored.push(this.urlPart(id, type, part.filename, meta));
    });
    yield this.status(TaskState.TASK_STATE_WORKING);
    if (stored.some((p) => p.content?.$case === "url")) yield this.echo(message.messageId, stored);
    await this.pause();
    for (const part of stored) {
      const meta = part.metadata ?? {};
      if (meta["voice"] === true && typeof meta["mediaId"] === "string") {
        yield this.artifact(`transcript:${meta["mediaId"]}`, "transcript", [textPart("Could the lamp be warmer too?")], { mediaId: meta["mediaId"] });
      }
    }
    const reply = voice
      ? "Yes: a 2700 K bulb in the floor lamp, and a second lamp low in the far corner."
      : "Noted. A rust rug and a warm lamp would do the most.";
    if (message.metadata?.["speak"] === true) yield this.speak();
    yield this.status(TaskState.TASK_STATE_INPUT_REQUIRED, reply);
  }

  async *subscribe(taskId: string): AsyncGenerator<StreamResponse> {
    await Promise.resolve();
    if (taskId !== MEDIA_ROOT) throw new Error(`task not found: ${taskId}`);
    yield { payload: { $case: "task", value: clone(this.task) } };
    for (const event of this.log.slice(1)) yield clone(event);
  }

  async cancel(): Promise<Task> {
    await Promise.resolve();
    this.status(TaskState.TASK_STATE_CANCELED, "canceled by you");
    return clone(this.task);
  }

  complete(): AsyncGenerator<StreamResponse> {
    const self = this;
    return (async function* () {
      await Promise.resolve();
      yield self.status(TaskState.TASK_STATE_COMPLETED, "completed by you");
    })();
  }

  async commands(): Promise<CommandSpec[]> {
    await Promise.resolve();
    return clone(MEDIA_COMMANDS);
  }

  async media(): Promise<MediaParams | null> {
    await Promise.resolve();
    return clone(FIXTURE_MEDIA);
  }

  /** The media route from memory. A spoken reply streams 100 ms of PCM every 100 ms for
   * 30 s (or breaks off after 0.4 s with `speech: "broken"`), like a growing object. */
  async getMedia(url: string, signal?: AbortSignal): Promise<Response> {
    await Promise.resolve();
    const id = url.split("/").pop() ?? "";
    if (this.speech.has(id)) return new Response(this.pcm(signal), { headers: { "content-type": PCM_MEDIA_TYPE } });
    const found = this.store.get(id);
    if (found === undefined) return new Response("not found", { status: 404 });
    return new Response(found.bytes.slice().buffer, { headers: { "content-type": found.mediaType } });
  }

  private pcm(signal?: AbortSignal): ReadableStream<Uint8Array> {
    const rate = 24_000;
    const broken = this.options.speech === "broken";
    let sent = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    return new ReadableStream<Uint8Array>({
      pull(controller) {
        return new Promise<void>((resolve) => {
          timer = setTimeout(() => {
            if (signal?.aborted) {
              controller.close();
            } else if (broken && sent >= 4) {
              controller.error(new TypeError("network error: the spoken reply broke off"));
            } else if (sent >= 300) {
              controller.close();
            } else {
              controller.enqueue(new Uint8Array(tone(rate, 0.1, sent * rate * 0.1).buffer));
              sent += 1;
            }
            resolve();
          }, sent === 0 ? 0 : 100);
        });
      },
      cancel() {
        clearTimeout(timer);
      },
    });
  }
}
