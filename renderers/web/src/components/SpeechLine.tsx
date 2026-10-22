/**
 * A spoken reply's line under the reply (issue-38 R4.1–R4.5): "Speaking…" with Stop while
 * it plays, "Spoken · 0:07", "Stopped at 0:03" or "Speech interrupted" after, each with
 * Replay (which requests the URL again, from its start), "Spoken reply" with Play when it
 * was not played here, and "Speech unavailable" when the server could not speak it.
 */
import type { JSX } from "react";
import { PlayIcon, RotateCcwIcon, SquareIcon, Volume2Icon, VolumeXIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { clock } from "../media";
import type { SpeechItemData } from "../model";

export interface SpeechUi {
  state: "idle" | "speaking" | "done" | "stopped" | "interrupted";
  playedMs: number;
}

function Wave(props: { live: boolean }): JSX.Element {
  return (
    <span className={cn("speech-wave inline-flex h-4 items-center gap-0.5", props.live && "speech-wave-live")} aria-hidden="true">
      {[40, 75, 55, 90, 35, 70, 50, 85, 45, 65].map((h, i) => (
        <i key={i} className="block w-0.5 rounded-full bg-current" style={{ height: `${h}%`, animationDelay: `${i * 90}ms` }} />
      ))}
    </span>
  );
}

export function SpeechLine(props: {
  item: SpeechItemData;
  ui: SpeechUi;
  onStop: () => void;
  onReplay: (item: SpeechItemData) => void;
}): JSX.Element {
  const { item, ui } = props;
  const replay = (
    <Button type="button" variant="outline" size="xs" aria-label="Replay spoken reply" onClick={() => props.onReplay(item)}>
      <RotateCcwIcon />
      Replay
    </Button>
  );
  let body: JSX.Element;
  if (item.state === "failed") {
    body = (
      <>
        <VolumeXIcon className="size-4" aria-hidden="true" />
        <span>Speech unavailable</span>
      </>
    );
  } else if (ui.state === "speaking") {
    body = (
      <>
        <Wave live />
        <span>Speaking…</span>
        <Button type="button" variant="outline" size="xs" aria-label="Stop speaking" onClick={props.onStop}>
          <SquareIcon />
          Stop
        </Button>
      </>
    );
  } else if (ui.state === "done") {
    body = (
      <>
        <Wave live={false} />
        <span>Spoken · {clock(ui.playedMs)}</span>
        {replay}
      </>
    );
  } else if (ui.state === "stopped") {
    body = (
      <>
        <Wave live={false} />
        <span>Stopped at {clock(ui.playedMs)}</span>
        {replay}
      </>
    );
  } else if (ui.state === "interrupted") {
    body = (
      <>
        <VolumeXIcon className="size-4" aria-hidden="true" />
        <span>Speech interrupted</span>
        {replay}
      </>
    );
  } else {
    body = (
      <>
        <Volume2Icon className="size-4" aria-hidden="true" />
        <span>Spoken reply</span>
        <Button type="button" variant="outline" size="xs" aria-label="Play spoken reply" onClick={() => props.onReplay(item)}>
          <PlayIcon />
          Play
        </Button>
      </>
    );
  }
  return (
    <div
      role="status"
      data-state={item.state === "failed" ? "failed" : ui.state}
      className={cn(
        "ml-1 inline-flex flex-wrap items-center gap-2 text-sm",
        ui.state === "speaking" && item.state !== "failed" ? "text-primary" : "text-muted-foreground",
      )}
    >
      {body}
    </div>
  );
}
