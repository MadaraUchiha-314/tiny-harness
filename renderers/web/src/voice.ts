/**
 * Voice in the browser (issue-38 R3, R4), on native APIs only: `Recorder` records the
 * microphone with `MediaRecorder` (WebM/Opus, or MP4 on Safari) and meters it with an
 * `AnalyserNode`; `PcmStreamPlayer` plays a spoken reply while it streams — 16-bit
 * little-endian PCM from the media route, converted to floats and scheduled back to back
 * on one `AudioContext` with about 100 ms of look-ahead. The microphone is opened by the
 * caller (`MicButton`, which guards the permission race) and closed after each recording.
 */
import { baseType } from "./media";

/** Seconds of audio scheduled ahead of the playhead. */
export const LOOKAHEAD = 0.1;
export const MAX_RECORDING_MS = 120_000;
/** Shorter recordings are discarded (R3.6). */
export const MIN_RECORDING_MS = 300;
/** A recording whose loudest moment stays under this RMS (of full scale) is silence. */
export const SILENCE_RMS = 0.005;

// --- playback -------------------------------------------------------------------------

/** The part of `AudioContext` the player uses (a fake in tests). */
export interface AudioContextLike {
  readonly currentTime: number;
  readonly destination: AudioNode | object;
  resume(): Promise<void>;
  createBuffer(channels: number, length: number, sampleRate: number): AudioBuffer | { duration: number; copyToChannel(data: Float32Array, channel: number): void };
  createBufferSource(): {
    buffer: unknown;
    connect(node: never): unknown;
    start(when: number): void;
    stop(): void;
    onended: (() => void) | null;
  };
}

export type PlayOutcome = "done" | "stopped" | "interrupted";

/** Signed 16-bit little-endian samples as floats in [-1, 1). */
export function pcm16ToFloat32(bytes: Uint8Array): Float32Array<ArrayBuffer> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength - (bytes.byteLength % 2));
  const out = new Float32Array(view.byteLength / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

export class PcmStreamPlayer {
  private ctx: AudioContextLike | null = null;
  private sources: Array<ReturnType<AudioContextLike["createBufferSource"]>> = [];
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  /** Bumped by every stop (and so every play): an older play sees it and ends "stopped". */
  private generation = 0;
  private startTime = 0;
  private endTime = 0;
  private active = false;

  constructor(private readonly createContext: () => AudioContextLike = () => new AudioContext() as unknown as AudioContextLike) {}

  /** Create (once) and resume the context; call it from a user gesture (a send, the mic
   * release, Replay), where browsers allow audio to start. */
  unlock(): AudioContextLike {
    this.ctx ??= this.createContext();
    void this.ctx.resume().catch(() => undefined);
    return this.ctx;
  }

  get playing(): boolean {
    return this.active;
  }

  /** How much of the reply has been heard, in milliseconds. */
  get playedMs(): number {
    if (this.ctx === null || this.endTime === 0) return 0;
    const now = Math.min(this.ctx.currentTime, this.endTime);
    return Math.max(0, Math.round((now - this.startTime) * 1000));
  }

  /** Play `response`'s body as it arrives. "done" once the last sample has played,
   * "stopped" after `stop()`, "interrupted" when the stream breaks off (the server closes
   * a failed or superseded reply before its end) or is refused. */
  async play(response: Response, fmt: { sampleRate: number; channels: number }): Promise<PlayOutcome> {
    this.stop();
    const generation = this.generation;
    const stopped = () => generation !== this.generation;
    if (!response.ok || response.body === null) return "interrupted";
    const ctx = this.unlock();
    const reader = response.body.getReader();
    this.reader = reader;
    this.active = true;
    this.startTime = 0;
    this.endTime = 0;
    let next = 0;
    let carry: Uint8Array = new Uint8Array(0);
    let last: Promise<void> = Promise.resolve();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (stopped()) return "stopped";
        if (done) break;
        let bytes = value;
        if (carry.length > 0) {
          bytes = new Uint8Array(carry.length + value.length);
          bytes.set(carry);
          bytes.set(value, carry.length);
        }
        const whole = bytes.length - (bytes.length % (2 * fmt.channels));
        carry = bytes.slice(whole);
        if (whole === 0) continue;
        const samples = pcm16ToFloat32(bytes.subarray(0, whole));
        const frames = samples.length / fmt.channels;
        const buffer = ctx.createBuffer(fmt.channels, frames, fmt.sampleRate);
        for (let channel = 0; channel < fmt.channels; channel += 1) {
          const data = fmt.channels === 1 ? samples : samples.filter((_, i) => i % fmt.channels === channel);
          buffer.copyToChannel(data, channel);
        }
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination as never);
        // Back to back; after an underrun, one look-ahead from now.
        const at = Math.max(next, ctx.currentTime + LOOKAHEAD);
        if (this.startTime === 0) this.startTime = at;
        source.start(at);
        next = at + buffer.duration;
        this.endTime = next;
        this.sources.push(source);
        last = new Promise<void>((resolve) => {
          source.onended = () => resolve();
        });
      }
    } catch {
      if (stopped()) return "stopped";
      // The scheduled audio would play on past the break, under a Replay (self-review 2.3).
      this.silence();
      this.finish();
      return "interrupted";
    } finally {
      if (this.reader === reader) this.reader = null;
    }
    await last;
    if (stopped()) return "stopped";
    this.finish();
    return "done";
  }

  /** Stop every queued source and the download. */
  stop(): void {
    this.generation += 1;
    this.silence();
    void this.reader?.cancel().catch(() => undefined);
    this.reader = null;
    this.finish();
  }

  /** Stop every scheduled source. */
  private silence(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // a source that never started
      }
    }
  }

  private finish(): void {
    this.sources = [];
    this.active = false;
  }
}

// --- recording ------------------------------------------------------------------------

/** The type `MediaRecorder` records in: WebM/Opus, else MP4 (Safari); "" lets it choose. */
export function recordingType(isTypeSupported: (type: string) => boolean): string {
  for (const type of ["audio/webm;codecs=opus", "audio/mp4"]) if (isTypeSupported(type)) return type;
  return "";
}

export interface Recording {
  blob: Blob;
  /** Without parameters (`audio/webm`), as the card lists input types. */
  mediaType: string;
  durationMs: number;
  filename: string;
}

/** What `MicButton` drives: `Recorder`, or a fake in tests. */
export interface RecorderLike {
  start(): void;
  stop(): Promise<Recording | null>;
  discard(): void;
  sample(): void;
  readonly level: number;
  readonly elapsedMs: number;
  onCap?: (() => void) | undefined;
}

interface MeterContext {
  createMediaStreamSource(stream: MediaStream): { connect(node: never): unknown };
  createAnalyser(): { fftSize: number; getFloatTimeDomainData(data: Float32Array): void };
  close(): Promise<void>;
}

export interface RecorderDeps {
  MediaRecorder: typeof MediaRecorder;
  createContext?: () => MeterContext;
  now?: () => number;
}

const EXTENSIONS: { [type: string]: string } = { "audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg" };

export class Recorder implements RecorderLike {
  onCap?: (() => void) | undefined;
  private readonly recorder: MediaRecorder;
  private readonly chunks: Blob[] = [];
  private readonly now: () => number;
  private meter: MeterContext | null = null;
  private analyser: ReturnType<MeterContext["createAnalyser"]> | null = null;
  private data: Float32Array<ArrayBuffer> | null = null;
  private startedAt = 0;
  private started = false;
  private peak = 0;
  private current = 0;
  private cap: ReturnType<typeof setTimeout> | undefined;
  private ticker: ReturnType<typeof setInterval> | undefined;
  private closed = false;
  private stoppedAt: number | null = null;

  constructor(
    private readonly stream: MediaStream,
    deps: RecorderDeps,
  ) {
    const Ctor = deps.MediaRecorder;
    const type = recordingType((t) => Ctor.isTypeSupported(t));
    this.recorder = new Ctor(stream, type ? { mimeType: type } : {});
    this.now = deps.now ?? (() => performance.now());
    try {
      const meter = deps.createContext?.() ?? null;
      if (meter !== null) {
        const analyser = meter.createAnalyser();
        analyser.fftSize = 2048;
        meter.createMediaStreamSource(stream).connect(analyser as never);
        this.meter = meter;
        this.analyser = analyser;
        this.data = new Float32Array(analyser.fftSize);
      }
    } catch {
      this.meter = null; // no meter: the recording still works, without the silence check
    }
  }

  /** The newest level, 0..1 (RMS of full scale). */
  get level(): number {
    return this.current;
  }

  get elapsedMs(): number {
    if (!this.started) return 0;
    return Math.round((this.stoppedAt ?? this.now()) - this.startedAt);
  }

  start(): void {
    this.recorder.ondataavailable = (e: BlobEvent | { data: Blob }) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.startedAt = this.now();
    this.started = true;
    this.recorder.start();
    this.cap = setTimeout(() => this.onCap?.(), MAX_RECORDING_MS);
    if (this.analyser !== null) this.ticker = setInterval(() => this.sample(), 50);
  }

  /** Read the meter once (the ticker calls it every 50 ms). */
  sample(): void {
    if (this.analyser === null || this.data === null) return;
    this.analyser.getFloatTimeDomainData(this.data);
    let sum = 0;
    for (const v of this.data) sum += v * v;
    this.current = Math.sqrt(sum / this.data.length);
    this.peak = Math.max(this.peak, this.current);
  }

  /** The recording, or null when it was shorter than 0.3 s or silent (R3.6). */
  async stop(): Promise<Recording | null> {
    const durationMs = this.elapsedMs;
    this.sample();
    const stopped = new Promise<void>((resolve) => {
      this.recorder.onstop = () => resolve();
    });
    if (this.recorder.state !== "inactive") this.recorder.stop();
    else this.recorder.onstop?.(new Event("stop"));
    await stopped;
    const silent = this.analyser !== null && this.peak < SILENCE_RMS;
    this.close();
    if (durationMs < MIN_RECORDING_MS || silent || this.chunks.length === 0) return null;
    const recorded = this.chunks[0]?.type || this.recorder.mimeType || "audio/webm";
    const mediaType = baseType(recorded);
    const blob = new Blob(this.chunks, { type: mediaType });
    return { blob, mediaType, durationMs, filename: `voice.${EXTENSIONS[mediaType] ?? "webm"}` };
  }

  discard(): void {
    this.recorder.ondataavailable = null;
    if (this.recorder.state !== "inactive") this.recorder.stop();
    this.chunks.length = 0;
    this.close();
  }

  private close(): void {
    if (this.closed) return;
    this.closed = true;
    this.stoppedAt = this.now();
    clearTimeout(this.cap);
    clearInterval(this.ticker);
    for (const track of this.stream.getTracks()) track.stop();
    void this.meter?.close().catch(() => undefined);
  }
}

/** The browser's `Recorder` on `stream`. */
export function browserRecorder(stream: MediaStream): RecorderLike {
  return new Recorder(stream, {
    MediaRecorder,
    createContext: () => new AudioContext() as unknown as MeterContext,
  });
}
