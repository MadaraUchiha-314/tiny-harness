/**
 * Media in the web renderer (issue-38): the types the server accepts, the `raw` file part a
 * file is sent in, the early check of a file against the card's limits, and the cache that
 * turns a media URL into a blob URL. A medium is only ever shown through `<img>` or
 * `<audio>` on a blob URL this module made, and only for an accepted raster image or audio
 * type: the type is checked on the item and again on the response (abuse case 6).
 */
import { PARTICIPANT_HEADER, type MediaParams, type Part } from "./a2a";

export type { MediaParams };
export type MediaKind = "image" | "audio";

/** The server's `ACCEPTED` (harness/media/models.py): raster images and audio only. */
export const ACCEPTED: ReadonlyMap<string, MediaKind> = new Map<string, MediaKind>([
  ["image/png", "image"],
  ["image/jpeg", "image"],
  ["image/webp", "image"],
  ["image/gif", "image"],
  ["audio/wav", "audio"],
  ["audio/mpeg", "audio"],
  ["audio/mp4", "audio"],
  ["audio/ogg", "audio"],
  ["audio/webm", "audio"],
]);

/** Spoken replies: raw PCM the server produces, never accepted as input. */
export const PCM_MEDIA_TYPE = "audio/L16;rate=24000;channels=1";
export const PCM_FORMAT = { sampleRate: 24_000, channels: 1 } as const;

/** `audio/webm;codecs=opus` → `audio/webm`. */
export function baseType(mediaType: string): string {
  return (mediaType.split(";")[0] ?? "").trim().toLowerCase();
}

/** `image` or `audio` for an accepted type or the speech type; null for anything else. */
export function mediaKind(mediaType: string): MediaKind | null {
  if (mediaType.replace(/\s/g, "").toLowerCase() === PCM_MEDIA_TYPE.toLowerCase()) return "audio";
  return ACCEPTED.get(baseType(mediaType)) ?? null;
}

export function isRaster(mediaType: string): boolean {
  return mediaKind(mediaType) === "image";
}

/**
 * The SDK serialises a `raw` part with `globalThis.Buffer.from(bytes).toString("base64")`,
 * which browsers lack. This is that one operation (and its inverse), nothing more; it is
 * installed only where no `Buffer` exists.
 */
export interface BufferLike {
  from(value: Uint8Array | ArrayLike<number> | string, encoding?: string): Uint8Array & { toString(encoding?: string): string };
  isBuffer(value: unknown): boolean;
}

export function bufferShim(): BufferLike {
  const brand = Symbol("tiny-harness.buffer");
  const wrap = (bytes: Uint8Array) => {
    const out = bytes as Uint8Array & { toString(encoding?: string): string; [brand]?: true };
    Object.defineProperty(out, brand, { value: true });
    Object.defineProperty(out, "toString", {
      value: (encoding?: string) => {
        if (encoding !== "base64") return new TextDecoder().decode(out);
        let binary = "";
        for (let i = 0; i < out.length; i += 0x8000) binary += String.fromCharCode(...out.subarray(i, i + 0x8000));
        return btoa(binary);
      },
    });
    return out;
  };
  return {
    from(value, encoding) {
      if (typeof value === "string") {
        if (encoding !== "base64") return wrap(new TextEncoder().encode(value));
        const binary = atob(value);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        return wrap(bytes);
      }
      return wrap(Uint8Array.from(value));
    },
    isBuffer: (value) => typeof value === "object" && value !== null && brand in value,
  };
}

export function installBufferShim(target: { Buffer?: unknown } = globalThis as { Buffer?: unknown }): void {
  if (target.Buffer === undefined) target.Buffer = bufferShim();
}

/** A file as a `raw` file part (the SDK base64-encodes it on the wire). */
export function filePart(
  bytes: Uint8Array,
  mediaType: string,
  filename: string,
  metadata?: { [key: string]: unknown },
): Part {
  installBufferShim();
  // The SDK types `raw` as Node's Buffer; it only reads the bytes.
  return { content: { $case: "raw", value: bytes as unknown as Buffer }, metadata, filename, mediaType };
}

/** A blob's bytes (`FileReader` where a `Blob` has no `arrayBuffer`, as in jsdom). */
export function blobBytes(blob: Blob): Promise<Uint8Array> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer().then((b) => new Uint8Array(b));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error ?? new Error("the file could not be read"));
    reader.readAsArrayBuffer(blob);
  });
}

// --- words ------------------------------------------------------------------------------

/** `940 KB`, `1.8 MB`, `48 MB` (binary units, as the TUI says them). */
export function humanSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  const mb = size / (1024 * 1024);
  return mb < 10 ? `${mb.toFixed(1)} MB` : `${Math.round(mb)} MB`;
}

/** A configured limit: `20 MiB` when it is whole mebibytes, else bytes. */
export function limitText(size: number): string {
  const mib = 1024 * 1024;
  return size >= mib && size % mib === 0 ? `${size / mib} MiB` : `${size} bytes`;
}

export function clock(durationMs: number): string {
  const seconds = Math.round(durationMs / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** The server's refusal of one file (`InvalidParams` data `reason`, `limit`), in words. */
export function rejectionText(name: string, size: number, reason: string, limit: string | null, fallback: string): string {
  if (reason === "too_large" && limit && /^\d+$/.test(limit)) {
    return `${name} is ${humanSize(size)}; the limit is ${limitText(Number(limit))} per file`;
  }
  if (reason === "message_too_large" && limit && /^\d+$/.test(limit)) {
    return `the files are larger than ${limitText(Number(limit))} per message`;
  }
  if (reason === "audio_too_long" && limit) return `${name} is longer than ${limit} s, the limit`;
  if (reason === "not_audio_only") return `${name} holds more than audio; only audio is accepted`;
  if (reason === "audio_codec_not_accepted") return `${name} uses an audio codec this agent does not accept`;
  if (reason === "type_not_accepted" || reason === "type_mismatch") return `${name} is not a file this agent accepts`;
  return fallback;
}

/** The checks the server makes that a browser can make first (type and size); null passes. */
export function checkFile(file: { name: string; size: number; type: string }, limits: MediaParams): string | null {
  const type = baseType(file.type);
  if (!ACCEPTED.has(type) || !limits.input.map(baseType).includes(type)) {
    return `${file.name} is not a file this agent accepts`;
  }
  if (limits.maxFileBytes > 0 && file.size > limits.maxFileBytes) {
    return `${file.name} is ${humanSize(file.size)}; the limit is ${limitText(limits.maxFileBytes)} per file`;
  }
  return null;
}

// --- fetching -----------------------------------------------------------------------------

/** GET a media URL with the participant's identity, as the media route requires. */
export function fetchMedia(url: string, participant: string, fetchImpl: typeof fetch = fetch): Promise<Response> {
  return fetchImpl(url, { headers: { [PARTICIPANT_HEADER]: participant } });
}

export type MediaLoader = (url: string) => Promise<Response>;

/**
 * Media URL → blob URL, fetched once per URL and kept until the task view goes
 * (`revokeAll`). The blob's type is the response's, and only when it is the accepted type
 * family the item declared: an SVG or HTML body never becomes a blob URL.
 */
export class MediaCache {
  private readonly urls = new Map<string, Promise<string>>();
  private readonly made = new Set<string>();
  private seq = 0;

  constructor(private readonly loader: MediaLoader) {}

  url(src: string, mediaType: string): Promise<string> {
    const known = this.urls.get(src);
    if (known) return known;
    if (src.startsWith("local:")) return Promise.reject(new Error(`unknown local medium ${src}`));
    const pending = this.load(src, mediaType);
    this.urls.set(src, pending);
    pending.catch(() => this.urls.delete(src));
    return pending;
  }

  /** A file the user is sending, shown at once under a `local:` key. */
  adopt(blob: Blob): string {
    this.seq += 1;
    const key = `local:${this.seq}`;
    this.urls.set(key, Promise.resolve(this.make(blob)));
    return key;
  }

  /** The stored URL of a file already shown from `key`: no second download. */
  alias(src: string, key: string): void {
    const known = this.urls.get(key);
    if (known && !this.urls.has(src)) this.urls.set(src, known);
  }

  /** Revoke the blob URL of a local file the server refused (self-review 2.5). */
  async release(key: string): Promise<void> {
    const known = this.urls.get(key);
    if (!known || !key.startsWith("local:")) return;
    this.urls.delete(key);
    const url = await known;
    URL.revokeObjectURL(url);
    this.made.delete(url);
  }

  revokeAll(): void {
    for (const url of this.made) URL.revokeObjectURL(url);
    this.made.clear();
    this.urls.clear();
  }

  private async load(src: string, mediaType: string): Promise<string> {
    const expected = mediaKind(mediaType);
    if (expected === null) throw new Error(`${mediaType} is not an accepted type`);
    const response = await this.loader(src);
    if (!response.ok) throw new Error(`the media route answered ${response.status}`);
    const served = response.headers.get("content-type") ?? "";
    if (mediaKind(served) !== expected) throw new Error(`${served || "no type"} is not an accepted ${expected} type`);
    const blob = new Blob([await response.arrayBuffer()], { type: served });
    return this.make(blob);
  }

  private make(blob: Blob): string {
    const url = URL.createObjectURL(blob);
    this.made.add(url);
    return url;
  }
}
