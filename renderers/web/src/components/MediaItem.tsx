/**
 * One image or audio file in a turn (issue-38 R2.3, R6.3). The bytes come only through the
 * blob URL `load` hands out, and only for an accepted raster image or audio type: an SVG,
 * HTML or any other type is named, never fetched or drawn, and nothing here is ever set as
 * HTML (abuse case 6). An image fits the column and opens full size in a dialog; a voice
 * turn shows its transcript underneath.
 */
import { useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import { ImageOffIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { clock, humanSize, isRaster, mediaKind } from "../media";
import type { MediaItemData } from "../model";

export type MediaLoad = (url: string, mediaType: string) => Promise<string>;

function allowed(item: MediaItemData): boolean {
  const kind = mediaKind(item.mediaType);
  if (kind !== item.media) return false;
  return kind === "audio" || isRaster(item.mediaType);
}

function caption(item: MediaItemData): string {
  const dims = item.width && item.height ? `${item.width}×${item.height}` : null;
  if (item.media === "image") {
    const parts = item.role === "agent" ? ["generated"] : [item.name];
    if (item.role !== "agent" && item.size) parts.push(humanSize(item.size));
    if (dims) parts.push(dims);
    return parts.join(" · ");
  }
  const label = item.voice ? "voice" : item.name;
  if (item.durationMs !== undefined) return `${label} · ${clock(item.durationMs)}`;
  return item.size ? `${label} · ${humanSize(item.size)}` : label;
}

export function MediaItem(props: { item: MediaItemData; load: MediaLoad }): JSX.Element {
  const { item, load } = props;
  const ok = allowed(item);
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const [zoomed, setZoomed] = useState(false);

  useEffect(() => {
    if (!ok) return;
    let live = true;
    setError(null);
    load(item.url, item.mediaType).then(
      (url) => {
        if (live) setSrc(url);
      },
      (reason: unknown) => {
        if (live) setError(reason instanceof Error ? reason.message : String(reason));
      },
    );
    return () => {
      live = false;
    };
  }, [ok, load, item.url, item.mediaType]);

  if (!ok) {
    return (
      <p data-testid="media-refused" className="flex items-center gap-2 text-sm text-muted-foreground">
        <ImageOffIcon className="size-4" aria-hidden="true" />
        Not shown: {item.name} ({item.mediaType}) is not an accepted image or audio type.
      </p>
    );
  }
  if (error !== null) {
    return (
      <p data-testid="media-error" className="flex items-center gap-2 text-sm text-muted-foreground">
        <ImageOffIcon className="size-4" aria-hidden="true" />
        {item.name} could not be shown: {error}
      </p>
    );
  }

  if (item.media === "image") {
    const alt = item.role === "agent" ? item.name : `Image ${item.name}`;
    const open = () => {
      const d = dialog.current;
      if (!d) return;
      setZoomed(true);
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
    };
    const close = () => {
      const d = dialog.current;
      if (!d) return;
      if (typeof d.close === "function") d.close();
      d.removeAttribute("open");
      setZoomed(false);
    };
    return (
      <figure className="m-0 flex w-[min(320px,100%)] flex-col gap-1" data-testid="media-image">
        <button
          type="button"
          onClick={open}
          aria-label={`Open ${item.name} full size`}
          disabled={src === null}
          className="block w-full cursor-zoom-in overflow-hidden rounded-lg border bg-muted outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {src !== null ? (
            <img src={src} alt={alt} className="block h-auto max-w-full" />
          ) : (
            <span className="block aspect-[4/3] w-full" aria-hidden="true" />
          )}
        </button>
        <figcaption className="text-xs text-muted-foreground">{caption(item)}</figcaption>
        <dialog
          ref={dialog}
          aria-label={item.name}
          onClose={() => setZoomed(false)}
          className="m-auto max-w-[min(90vw,1200px)] rounded-xl border bg-background p-3 text-foreground backdrop:bg-black/60"
        >
          {zoomed && src !== null ? <img src={src} alt={alt} className="block h-auto max-h-[80vh] max-w-full" /> : null}
          <div className="mt-2 flex justify-end">
            <Button type="button" variant="outline" size="sm" onClick={close}>
              Close
            </Button>
          </div>
        </dialog>
      </figure>
    );
  }

  return (
    <figure className="m-0 flex flex-col gap-1" data-testid="media-audio">
      {src !== null ? (
        <audio controls preload="metadata" src={src} aria-label={caption(item)} className="h-10 w-[min(300px,100%)]" />
      ) : (
        <span className="block h-10 w-[min(300px,100%)] rounded-full bg-muted" aria-hidden="true" />
      )}
      <figcaption className="text-xs text-muted-foreground">{caption(item)}</figcaption>
      {item.voice ? (
        <p data-testid="transcript" className="m-0 mt-1 border-l-2 pl-2.5 italic">
          {item.transcript !== undefined ? `“${item.transcript}”` : "Transcribing…"}
        </p>
      ) : null}
    </figure>
  );
}
