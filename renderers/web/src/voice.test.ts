import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CHUNK_SECONDS,
  LOOKAHEAD,
  MAX_AHEAD,
  MAX_RECORDING_MS,
  PcmStreamPlayer,
  Recorder,
  pcm16ToFloat32,
  recordingType,
  type AudioContextLike,
} from "./voice";

// --- a fake Web Audio graph ------------------------------------------------------------

interface FakeSource {
  buffer: { samples: Float32Array; duration: number } | null;
  startedAt: number | null;
  stopped: boolean;
  disconnected: boolean;
  onended: (() => void) | null;
}

function fakeContext() {
  const sources: FakeSource[] = [];
  const ctx = {
    currentTime: 0,
    state: "running",
    destination: {},
    resumed: 0,
    resume() {
      this.resumed += 1;
      return Promise.resolve();
    },
    createBuffer(channels: number, length: number, sampleRate: number) {
      const samples = new Float32Array(length);
      return {
        duration: length / sampleRate,
        numberOfChannels: channels,
        getChannelData: () => samples,
        copyToChannel: (data: Float32Array) => samples.set(data),
        samples,
      };
    },
    createBufferSource() {
      const source = {
        buffer: null as FakeSource["buffer"],
        startedAt: null as number | null,
        stopped: false,
        disconnected: false,
        onended: null as (() => void) | null,
        connect: () => undefined,
        disconnect() {
          source.disconnected = true;
        },
        start(at: number) {
          source.startedAt = at;
        },
        stop() {
          source.stopped = true;
          source.onended?.();
        },
      };
      sources.push(source);
      return source;
    },
  };
  return { ctx: ctx as unknown as AudioContextLike & typeof ctx, sources };
}

/** A response whose body yields `chunks`, then ends or breaks. */
function streamed(chunks: Uint8Array[], end: "close" | "error" | "hang" = "close"): Response {
  let at = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      const chunk = chunks[at++];
      if (chunk !== undefined) controller.enqueue(chunk);
      else if (end === "close") controller.close();
      else if (end === "error") controller.error(new TypeError("network error"));
      else return new Promise<void>(() => undefined);
      return undefined;
    },
  });
  return new Response(body);
}

const samples = (n: number, value = 0x1000) => {
  const bytes = new Uint8Array(n * 2);
  for (let i = 0; i < n; i += 1) {
    bytes[i * 2] = value & 0xff;
    bytes[i * 2 + 1] = (value >> 8) & 0xff;
  }
  return bytes;
};
const FMT = { sampleRate: 24_000, channels: 1 };
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("pcm16ToFloat32", () => {
  it("reads signed 16-bit little-endian samples as floats in [-1, 1)", () => {
    const out = pcm16ToFloat32(new Uint8Array([0x00, 0x80, 0xff, 0x7f, 0x00, 0x00, 0x00, 0x40]));
    expect(Array.from(out)).toEqual([-1, 32767 / 32768, 0, 0.5]);
  });
});

describe("PcmStreamPlayer", () => {
  it("schedules each chunk back to back, starting one look-ahead from now", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    const done = player.play(streamed([samples(2400), samples(2400), samples(1200)]), FMT);
    await flush();
    await flush();
    expect(sources.map((s) => s.startedAt)).toEqual([LOOKAHEAD, LOOKAHEAD + 0.1, LOOKAHEAD + 0.2]);
    expect(sources[0]?.buffer?.samples[0]).toBe(0x1000 / 32768);
    expect(player.playing).toBe(true);
    sources.forEach((s) => s.onended?.());
    await expect(done).resolves.toBe("done");
    expect(player.playing).toBe(false);
  });

  it("keeps a sample split across two chunks", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    const whole = samples(2);
    const done = player.play(streamed([whole.subarray(0, 3), whole.subarray(3)]), FMT);
    await flush();
    await flush();
    const total = sources.reduce((n, s) => n + (s.buffer?.samples.length ?? 0), 0);
    expect(total).toBe(2);
    sources.forEach((s) => s.onended?.());
    await done;
  });

  it("restarts the schedule one look-ahead ahead after an underrun", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    let n = 0;
    const body = new ReadableStream<Uint8Array>({
      async pull(controller) {
        n += 1;
        if (n === 1) controller.enqueue(samples(2400));
        else if (n === 2) {
          await gate;
          controller.enqueue(samples(2400));
        } else controller.close();
      },
    });
    const done = player.play(new Response(body), FMT);
    await flush();
    ctx.currentTime = 5; // the first chunk played long ago
    release?.();
    await flush();
    await flush();
    expect(sources.map((s) => s.startedAt)).toEqual([LOOKAHEAD, 5 + LOOKAHEAD]);
    sources.forEach((s) => s.onended?.());
    await done;
  });

  it("stop() stops every queued source and ends the stream as stopped", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    const done = player.play(streamed([samples(2400), samples(2400)], "hang"), FMT);
    await flush();
    await flush();
    expect(sources).toHaveLength(2);
    player.stop();
    await expect(done).resolves.toBe("stopped");
    expect(sources.every((s) => s.stopped)).toBe(true);
    expect(player.playing).toBe(false);
  });

  it("calls a stream that breaks off interrupted, and a refused one too", async () => {
    const { ctx } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    await expect(player.play(streamed([samples(10)], "error"), FMT)).resolves.toBe("interrupted");
    await expect(player.play(new Response("gone", { status: 404 }), FMT)).resolves.toBe("interrupted");
  });

  it("stops every scheduled source when the stream breaks off, so a Replay never overlaps it", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    await expect(player.play(streamed([samples(2400), samples(2400)], "error"), FMT)).resolves.toBe("interrupted");
    expect(sources).toHaveLength(2);
    expect(sources.every((s) => s.stopped)).toBe(true);
    const replay = player.play(streamed([samples(2400)]), FMT);
    await flush();
    await flush();
    expect(sources.slice(0, 2).every((s) => s.stopped)).toBe(true);
    expect(sources[2]?.stopped).toBe(false);
    sources[2]?.onended?.();
    await expect(replay).resolves.toBe("done");
  });

  it("splits a big chunk into buffers of at most 0.5 s (critic 7)", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    const done = player.play(streamed([samples(24_000 + 4_800)]), FMT);
    await flush();
    await flush();
    expect(sources.map((s) => s.buffer?.samples.length)).toEqual([12_000, 12_000, 4_800]);
    expect(sources.map((s) => s.startedAt)).toEqual([LOOKAHEAD, LOOKAHEAD + 0.5, LOOKAHEAD + 1]);
    sources.forEach((s) => s.onended?.());
    await expect(done).resolves.toBe("done");
    expect(CHUNK_SECONDS).toBe(0.5);
  });

  it("reads no further while more than 2 s is scheduled ahead of the playhead (critic 7)", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    let pulled = 0;
    const body = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          pulled += 1;
          if (pulled > 40) controller.close();
          else controller.enqueue(samples(12_000)); // 0.5 s each
        },
      },
      { highWaterMark: 0 },
    );
    const done = player.play(new Response(body), FMT);
    for (let i = 0; i < 10; i += 1) await flush();
    // 0.1 s look-ahead + 0.5 s per buffer: after the fourth, 2.1 s is scheduled ahead.
    expect(sources).toHaveLength(4);
    expect(pulled).toBeLessThanOrEqual(5);
    // The playhead moves past the first buffer; it ends, and reading goes on to 2.5 s ahead.
    ctx.currentTime = 0.6;
    sources[0]?.onended?.();
    for (let i = 0; i < 10; i += 1) await flush();
    expect(sources).toHaveLength(6);
    player.stop();
    await expect(done).resolves.toBe("stopped");
    expect(MAX_AHEAD).toBe(2);
  });

  it("disconnects each source when it ends and does not stop it again (critic 7)", async () => {
    const { ctx, sources } = fakeContext();
    const player = new PcmStreamPlayer(() => ctx);
    const done = player.play(streamed([samples(2400), samples(2400)], "hang"), FMT);
    await flush();
    await flush();
    sources[0]?.onended?.();
    expect(sources[0]?.disconnected).toBe(true);
    expect(sources[1]?.disconnected).toBe(false);
    player.stop();
    await expect(done).resolves.toBe("stopped");
    expect(sources[0]?.stopped).toBe(false);
    expect(sources[1]?.stopped).toBe(true);
  });

  it("creates and resumes one context on unlock, from the user's gesture", () => {
    const { ctx } = fakeContext();
    const create = vi.fn(() => ctx);
    const player = new PcmStreamPlayer(create);
    player.unlock();
    player.unlock();
    expect(create).toHaveBeenCalledTimes(1);
    expect(ctx.resumed).toBe(2);
  });
});

// --- the recorder ---------------------------------------------------------------------

class FakeTrack {
  stopped = false;
  stop() {
    this.stopped = true;
  }
}

function fakeStream() {
  const tracks = [new FakeTrack()];
  return { stream: { getTracks: () => tracks } as unknown as MediaStream, tracks };
}

class FakeMediaRecorder {
  static supported = new Set(["audio/webm;codecs=opus", "audio/mp4"]);
  static isTypeSupported(type: string) {
    return FakeMediaRecorder.supported.has(type);
  }
  static last: FakeMediaRecorder | null = null;
  state = "inactive";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(
    readonly stream: MediaStream,
    readonly options: { mimeType?: string },
  ) {
    FakeMediaRecorder.last = this;
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob([new Uint8Array([0x1a, 0x45, 0xdf, 0xa3])], { type: this.options.mimeType ?? "" }) });
    this.onstop?.();
  }
}

function recorderWith(level: number) {
  let now = 0;
  const { stream, tracks } = fakeStream();
  const analyser = {
    fftSize: 2048,
    getFloatTimeDomainData: (data: Float32Array) => data.fill(level),
  };
  const audio = {
    createMediaStreamSource: () => ({ connect: () => undefined }),
    createAnalyser: () => analyser,
    close: vi.fn(() => Promise.resolve()),
  };
  const recorder = new Recorder(stream, {
    MediaRecorder: FakeMediaRecorder as unknown as typeof MediaRecorder,
    createContext: () => audio,
    now: () => now,
  });
  return { recorder, tracks, audio, advance: (ms: number) => (now += ms) };
}

describe("Recorder", () => {
  afterEach(() => vi.useRealTimers());

  it("records WebM/Opus, else MP4 (Safari)", () => {
    expect(recordingType((t) => t === "audio/webm;codecs=opus" || t === "audio/mp4")).toBe("audio/webm;codecs=opus");
    expect(recordingType((t) => t === "audio/mp4")).toBe("audio/mp4");
    expect(recordingType(() => false)).toBe("");
  });

  it("returns the recording, its type and duration, and closes the microphone", async () => {
    const { recorder, tracks, audio, advance } = recorderWith(0.2);
    recorder.start();
    expect(FakeMediaRecorder.last?.options.mimeType).toBe("audio/webm;codecs=opus");
    advance(1500);
    recorder.sample();
    expect(recorder.level).toBeCloseTo(0.2);
    expect(recorder.elapsedMs).toBe(1500);
    const recording = await recorder.stop();
    expect(recording?.mediaType).toBe("audio/webm");
    expect(recording?.durationMs).toBe(1500);
    expect(recording?.filename).toBe("voice.webm");
    expect(recording?.blob.size).toBe(4);
    expect(tracks.every((t) => t.stopped)).toBe(true);
    expect(audio.close).toHaveBeenCalled();
  });

  it("discards a recording shorter than 0.3 s or silent", async () => {
    const short = recorderWith(0.2);
    short.recorder.start();
    short.advance(200);
    await expect(short.recorder.stop()).resolves.toBeNull();
    expect(short.tracks.every((t) => t.stopped)).toBe(true);

    const silent = recorderWith(0.0005);
    silent.recorder.start();
    silent.advance(2000);
    silent.recorder.sample();
    await expect(silent.recorder.stop()).resolves.toBeNull();
  });

  it("stops at the 120 s cap", () => {
    vi.useFakeTimers();
    const { recorder } = recorderWith(0.2);
    const cap = vi.fn();
    recorder.onCap = cap;
    recorder.start();
    vi.advanceTimersByTime(MAX_RECORDING_MS - 1);
    expect(cap).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(cap).toHaveBeenCalledTimes(1);
  });

  it("discard() closes the microphone and keeps nothing", () => {
    const { recorder, tracks } = recorderWith(0.2);
    recorder.start();
    recorder.discard();
    expect(tracks.every((t) => t.stopped)).toBe(true);
    expect(FakeMediaRecorder.last?.state).toBe("inactive");
  });
});
