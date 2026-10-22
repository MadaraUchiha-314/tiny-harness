import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MEDIA_EXT_URI, PARTICIPANT_HEADER, commandsOf, mediaOf, userMessage } from "./a2a";
import {
  ACCEPTED,
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
