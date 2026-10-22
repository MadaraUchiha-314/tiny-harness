import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HarnessClient, MEDIA_EXT_URI, PARTICIPANT_HEADER, commandsOf, mediaOf, mediaRoute, userMessage } from "./a2a";
import {
  ACCEPTED,
  MAX_DOWNLOADS,
  MEDIA_CACHE_BUDGET,
  MediaCache,
  PCM_MEDIA_TYPE,
  baseType,
  bufferShim,
  checkFile,
  clock,
  fetchMedia,
  filePart,
  humanSize,
  isRaster,
  mediaKind,
  rejectionText,
  type MediaParams,
} from "./media";

const LIMITS: MediaParams = {
  input: ["image/png", "image/jpeg", "image/webp", "image/gif", "audio/wav", "audio/webm"],
  output: ["image/png", PCM_MEDIA_TYPE],
  maxFileBytes: 20 * 1024 * 1024,
  maxMessageBytes: 25 * 1024 * 1024,
  maxAudioSeconds: 120,
  speechToText: true,
  textToSpeech: true,
  imageGeneration: true,
  mediaPath: "/media",
};

describe("media types", () => {
  it("accepts the server's raster images and audio, and nothing else", () => {
    expect([...ACCEPTED.keys()]).toEqual([
      "image/png",
      "image/jpeg",
      "image/webp",
      "image/gif",
      "audio/wav",
      "audio/mpeg",
      "audio/mp4",
      "audio/ogg",
      "audio/webm",
    ]);
    expect(mediaKind("image/svg+xml")).toBeNull();
    expect(mediaKind("text/html")).toBeNull();
    expect(mediaKind(PCM_MEDIA_TYPE)).toBe("audio");
    expect(mediaKind("audio/webm;codecs=opus")).toBe("audio");
    expect(isRaster("image/png")).toBe(true);
    expect(isRaster("image/svg+xml")).toBe(false);
    expect(baseType(" Audio/WebM; codecs=opus")).toBe("audio/webm");
  });
});

describe("filePart", () => {
  it("builds a raw file part with the type, the name and the metadata", () => {
    const bytes = new Uint8Array([137, 80, 78, 71]);
    const part = filePart(bytes, "image/png", "room.png", { voice: true, durationMs: 1200 });
    expect(part.content?.$case).toBe("raw");
    expect(Array.from(part.content?.value as Uint8Array)).toEqual([137, 80, 78, 71]);
    expect(part.mediaType).toBe("image/png");
    expect(part.filename).toBe("room.png");
    expect(part.metadata).toEqual({ voice: true, durationMs: 1200 });
  });

  it("sends the speaker setting on the message", () => {
    expect(userMessage({ text: "hi", contextId: "c", speak: true }).metadata).toEqual({ speak: true });
    expect(userMessage({ text: "hi", contextId: "c", participant: "you", speak: false }).metadata).toEqual({
      participant_id: "you",
      speak: false,
    });
  });
});

describe("the browser Buffer the SDK serialises raw parts with", () => {
  it("encodes to and decodes from base64", () => {
    const shim = bufferShim();
    const bytes = new Uint8Array([0, 1, 2, 250, 251, 252, 253, 254, 255]);
    const encoded = shim.from(bytes).toString("base64");
    expect(encoded).toBe(globalThis.Buffer.from(bytes).toString("base64"));
    expect(Array.from(shim.from(encoded, "base64"))).toEqual(Array.from(bytes));
    expect(shim.isBuffer(shim.from(bytes))).toBe(true);
    expect(shim.isBuffer(bytes)).toBe(false);
  });
});

describe("checkFile against the card", () => {
  it("accepts a file the card accepts", () => {
    expect(checkFile({ name: "room.jpg", size: 1_800_000, type: "image/jpeg" }, LIMITS)).toBeNull();
  });

  it("refuses a type the card does not list, SVG among them", () => {
    expect(checkFile({ name: "logo.svg", size: 900, type: "image/svg+xml" }, LIMITS)).toBe(
      "logo.svg is not a file this agent accepts",
    );
    expect(checkFile({ name: "clip.mp4", size: 900, type: "video/mp4" }, LIMITS)).toBe(
      "clip.mp4 is not a file this agent accepts",
    );
  });

  it("refuses a file over the per-file limit, naming the size and the limit", () => {
    expect(checkFile({ name: "big.png", size: 48 * 1024 * 1024, type: "image/png" }, LIMITS)).toBe(
      "big.png is 48 MB; the limit is 20 MiB per file",
    );
  });

  it("says sizes and durations the way the TUI does", () => {
    expect(humanSize(900)).toBe("900 B");
    expect(humanSize(940 * 1024)).toBe("940 KB");
    expect(humanSize(1.8 * 1024 * 1024)).toBe("1.8 MB");
    expect(clock(4_200)).toBe("0:04");
    expect(clock(72_000)).toBe("1:12");
  });

  it("words the server's refusal reasons", () => {
    expect(rejectionText("photo.png", 900, "type_mismatch", null, "x")).toBe("photo.png is not a file this agent accepts");
    expect(rejectionText("a.wav", 900, "audio_too_long", "120", "x")).toBe("a.wav is longer than 120 s, the limit");
    expect(rejectionText("a.png", 30 * 1024 * 1024, "too_large", String(20 * 1024 * 1024), "x")).toBe(
      "a.png is 30 MB; the limit is 20 MiB per file",
    );
    expect(rejectionText("memo.ogg", 1, "audio_codec_not_accepted", null, "x")).toBe(
      "memo.ogg uses an audio codec this agent does not accept",
    );
    expect(rejectionText("a.png", 1, "media_off", null, "fallback")).toBe("fallback");
  });
});

describe("the card's media extension", () => {
  it("reads the params, and none without the extension", () => {
    const card = { capabilities: { extensions: [{ uri: MEDIA_EXT_URI, params: { ...LIMITS } }] } };
    expect(mediaOf(card)).toEqual(LIMITS);
    expect(mediaOf({ capabilities: { extensions: [] } })).toBeNull();
  });

  it("keeps a command's runsOn", () => {
    const card = {
      capabilities: {
        extensions: [
          {
            uri: "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/commands/v1",
            params: { commands: [{ name: "attach", description: "Attach", argument_hint: "<path>", runsOn: "surface" }] },
          },
        ],
      },
    };
    expect(commandsOf(card)).toEqual([{ name: "attach", description: "Attach", argument_hint: "<path>", runsOn: "surface" }]);
  });
});

describe("fetching media", () => {
  it("sends the participant header", async () => {
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response("x", { headers: { "content-type": "image/png" } }));
    await fetchMedia("http://h/media/t/m", "you", fetchImpl);
    const init = fetchImpl.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(new Headers(init?.headers).get(PARTICIPANT_HEADER)).toBe("you");
  });
});

describe("MediaCache", () => {
  let made: Blob[];
  let revoked: string[];
  beforeEach(() => {
    made = [];
    revoked = [];
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: (blob: Blob) => {
        made.push(blob);
        return `blob:test/${made.length}`;
      },
      revokeObjectURL: (url: string) => {
        revoked.push(url);
      },
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  const png = () => new Response(new Uint8Array([137, 80, 78, 71]), { headers: { "content-type": "image/png" } });

  it("fetches a URL once and hands out a blob URL of the stated type", async () => {
    const loader = vi.fn(async () => png());
    const cache = new MediaCache(loader);
    const first = await cache.url("http://h/media/t/a", "image/png");
    const second = await cache.url("http://h/media/t/a", "image/png");
    expect(first).toBe("blob:test/1");
    expect(second).toBe(first);
    expect(loader).toHaveBeenCalledTimes(1);
    expect(made[0]?.type).toBe("image/png");
  });

  it("refuses a body served as SVG or HTML even when the item said PNG", async () => {
    const cache = new MediaCache(async () => new Response("<svg/>", { headers: { "content-type": "image/svg+xml" } }));
    await expect(cache.url("http://h/media/t/s", "image/png")).rejects.toThrow(/not an accepted/);
    const html = new MediaCache(async () => new Response("<p>", { headers: { "content-type": "text/html" } }));
    await expect(html.url("http://h/media/t/h", "image/png")).rejects.toThrow(/not an accepted/);
    expect(made).toHaveLength(0);
  });

  it("refuses a failed fetch", async () => {
    const cache = new MediaCache(async () => new Response("", { status: 404 }));
    await expect(cache.url("http://h/media/t/x", "image/png")).rejects.toThrow(/404/);
  });

  it("adopts a local file under a key, aliases the server URL to it, and revokes all", async () => {
    const loader = vi.fn(async () => png());
    const cache = new MediaCache(loader);
    const key = cache.adopt(new Blob([new Uint8Array([1])], { type: "image/png" }));
    expect(key).toMatch(/^local:/);
    expect(await cache.url(key, "image/png")).toBe("blob:test/1");
    cache.alias("http://h/media/t/a", key);
    expect(await cache.url("http://h/media/t/a", "image/png")).toBe("blob:test/1");
    expect(loader).not.toHaveBeenCalled();
    await expect(cache.url("local:unknown", "image/png")).rejects.toThrow();
    cache.revokeAll();
    expect(revoked).toEqual(["blob:test/1"]);
  });

  it("releases a local file's blob URL, once and only that one", async () => {
    const cache = new MediaCache(async () => png());
    const kept = cache.adopt(new Blob([new Uint8Array([1])], { type: "image/png" }));
    const gone = cache.adopt(new Blob([new Uint8Array([2])], { type: "image/png" }));
    await cache.release(gone);
    expect(revoked).toEqual(["blob:test/2"]);
    await expect(cache.url(gone, "image/png")).rejects.toThrow();
    expect(await cache.url(kept, "image/png")).toBe("blob:test/1");
    cache.revokeAll();
    expect(revoked).toEqual(["blob:test/2", "blob:test/1"]);
  });
});

describe("MediaCache memory budget (issue-38 critic 6)", () => {
  let made: Blob[];
  let revoked: string[];
  beforeEach(() => {
    made = [];
    revoked = [];
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: (blob: Blob) => {
        made.push(blob);
        return `blob:test/${made.length}`;
      },
      revokeObjectURL: (url: string) => {
        revoked.push(url);
      },
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  const bytes = (n: number, type = "image/png") => new Response(new Uint8Array(n), { headers: { "content-type": type } });

  /** A body of 2 MiB in 1 KiB chunks, with no Content-Length. */
  const endless = () => {
    let cancelled = false;
    let pulled = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulled += 1;
        if (pulled > 2048) controller.close();
        else controller.enqueue(new Uint8Array(1024));
      },
      cancel() {
        cancelled = true;
      },
    });
    return { response: new Response(body, { headers: { "content-type": "image/png" } }), cancelled: () => cancelled, pulled: () => pulled };
  };

  const deferred = () => {
    let resolve!: (r: Response) => void;
    const promise = new Promise<Response>((r) => (resolve = r));
    return { promise, resolve };
  };

  it("stops a download that streams past the card's per-file limit", async () => {
    const stream = endless();
    const cache = new MediaCache(async () => stream.response, { maxFileBytes: 10 * 1024 });
    await expect(cache.url("http://h/media/t/big", "image/png")).rejects.toThrow(/limit/);
    expect(stream.cancelled()).toBe(true);
    expect(stream.pulled()).toBeLessThan(20);
    expect(made).toHaveLength(0);
  });

  it("refuses at once a response whose Content-Length is over the limit", async () => {
    const loader = vi.fn(async () => new Response(new Uint8Array(64), { headers: { "content-type": "image/png", "content-length": "64" } }));
    const cache = new MediaCache(loader, { maxFileBytes: 32 });
    await expect(cache.url("http://h/media/t/cl", "image/png")).rejects.toThrow(/limit/);
    expect(made).toHaveLength(0);
  });

  it("runs at most four downloads at once and queues the rest", async () => {
    const waiting: Array<ReturnType<typeof deferred>> = [];
    const loader = vi.fn(() => {
      const d = deferred();
      waiting.push(d);
      return d.promise;
    });
    const cache = new MediaCache(loader);
    const all = [1, 2, 3, 4, 5, 6].map((n) => cache.url(`http://h/media/t/m${n}`, "image/png"));
    await Promise.resolve();
    await Promise.resolve();
    expect(loader).toHaveBeenCalledTimes(4);
    waiting[0]?.resolve(bytes(4));
    await all[0];
    await new Promise((r) => setTimeout(r, 0));
    expect(loader).toHaveBeenCalledTimes(5);
    waiting.slice(1).forEach((d) => d.resolve(bytes(4)));
    await new Promise((r) => setTimeout(r, 0));
    waiting.slice(4).forEach((d) => d.resolve(bytes(4)));
    await Promise.all(all);
    expect(loader).toHaveBeenCalledTimes(6);
  });

  it("evicts the least recently used blob past the byte budget and revokes its URL", async () => {
    const loader = vi.fn(async () => bytes(6));
    const cache = new MediaCache(loader, { budgetBytes: 13 });
    expect(await cache.url("http://h/media/t/a", "image/png")).toBe("blob:test/1");
    expect(await cache.url("http://h/media/t/b", "image/png")).toBe("blob:test/2");
    await cache.url("http://h/media/t/a", "image/png"); // a is now the most recent
    expect(await cache.url("http://h/media/t/c", "image/png")).toBe("blob:test/3");
    expect(revoked).toEqual(["blob:test/2"]);
    expect(loader).toHaveBeenCalledTimes(3);
    expect(await cache.url("http://h/media/t/b", "image/png")).toBe("blob:test/4"); // fetched again
    expect(loader).toHaveBeenCalledTimes(4);
    expect(revoked).toEqual(["blob:test/2", "blob:test/1"]);
  });

  it("caps the cache at 200 MiB by default", () => {
    expect(MEDIA_CACHE_BUDGET).toBe(200 * 1024 * 1024);
    expect(MAX_DOWNLOADS).toBe(4);
  });

  it("aborts the outstanding downloads, queued ones too, when the task view goes", async () => {
    const signals: AbortSignal[] = [];
    const loader = vi.fn((_url: string, _taskId: string, signal?: AbortSignal) => {
      if (signal) signals.push(signal);
      return new Promise<Response>(() => undefined);
    });
    const cache = new MediaCache(loader);
    const all = [1, 2, 3, 4, 5].map((n) => cache.url(`http://h/media/t/q${n}`, "image/png"));
    all.forEach((p) => p.catch(() => undefined));
    await Promise.resolve();
    await Promise.resolve();
    expect(signals).toHaveLength(4);
    cache.revokeAll();
    expect(signals.every((s) => s.aborted)).toBe(true);
    await Promise.allSettled(all);
    expect(loader).toHaveBeenCalledTimes(4);
    for (const p of all) await expect(p).rejects.toThrow();
  });
});

describe("a media URL is pinned to the task on screen (issue-38 critic 8)", () => {
  const BASE = "http://h:8080";
  const TASK = "9c41aa00-0000-0000-0000-00000000e07b";

  it("reads only this agent's exact media route, with valid ids", () => {
    expect(mediaRoute(`${BASE}/media/${TASK}/Qm3x_k-2`, BASE, "/media")).toEqual({ taskId: TASK, mediaId: "Qm3x_k-2" });
    expect(mediaRoute(`/media/${TASK}/Qm3x`, BASE, "/media")).toEqual({ taskId: TASK, mediaId: "Qm3x" });
    for (const url of [
      `http://evil.example/media/${TASK}/Qm3x`, // another origin
      `https://h:8080/media/${TASK}/Qm3x`, // another scheme
      `${BASE}/x/media/${TASK}/Qm3x`, // another path
      `${BASE}/media/${TASK}/Qm3x/more`,
      `${BASE}/media/${TASK}`,
      `${BASE}/media/${TASK}/bad.id`,
      `${BASE}/media/${TASK}/Qm3x?download=1`,
      `${BASE}/media/${TASK}/Qm3x#frag`,
      `${BASE}/media/${TASK}/Qm%2Fx`,
      `${BASE}/mediaX/${TASK}/Qm3x`,
    ]) {
      expect(mediaRoute(url, BASE, "/media"), url).toBeNull();
    }
  });

  class CardClient extends HarnessClient {
    override async media(): Promise<MediaParams | null> {
      return LIMITS;
    }
  }

  it("refuses another task's medium, and fetches the task's own with the participant header", async () => {
    const fetchSpy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("x", { headers: { "content-type": "image/png" } }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const client = new CardClient(BASE, "you");
      const other = `${BASE}/media/0ther-task/Qm3x`;
      await expect(client.getMedia(other, TASK)).rejects.toThrow(/not a media URL of task/);
      await expect(client.getMedia(`http://evil.example/media/${TASK}/Qm3x`, TASK)).rejects.toThrow();
      await expect(client.getMedia(`${BASE}/x/media/${TASK}/Qm3x`, TASK)).rejects.toThrow();
      expect(fetchSpy).not.toHaveBeenCalled();
      await client.getMedia(`${BASE}/media/${TASK}/Qm3x`, TASK);
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      expect(String(fetchSpy.mock.calls[0]?.[0])).toBe(`${BASE}/media/${TASK}/Qm3x`);
      expect(new Headers(fetchSpy.mock.calls[0]?.[1]?.headers).get(PARTICIPANT_HEADER)).toBe("you");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("asks the loader for the medium of the task the view shows", async () => {
    const loader = vi.fn(async (_url: string, _taskId: string) => new Response(new Uint8Array(4), { headers: { "content-type": "image/png" } }));
    const cache = new MediaCache(loader);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:test/1", revokeObjectURL: () => undefined }));
    try {
      await cache.url(`${BASE}/media/${TASK}/Qm3x`, "image/png", TASK);
      expect(loader.mock.calls[0]?.[1]).toBe(TASK);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
