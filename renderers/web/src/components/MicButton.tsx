/**
 * Hold to talk (issue-38 R3.1, R3.3, R3.5, R3.6; design critic 10). A pointer records
 * while the button is held (`pointerdown` … `pointerup` / `pointercancel` /
 * `pointerleave`); from the keyboard, Space or Enter toggles. The state is `aria-pressed`
 * and is announced in an assertive live region ("Recording", "Sent", "Nothing recorded").
 *
 * The acquisition race: `getUserMedia` may wait on a permission prompt. The button keeps
 * `want` and a generation that every start, stop and unmount bumps; when the grant
 * arrives it is used only if `want` still holds, the generation is the one that asked and
 * the button is mounted — otherwise every track is stopped at once and the stream
 * dropped, so the microphone is never live after a release, a toggle-off or an unmount.
 * Recording (and the indicator) starts only after that check.
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { JSX } from "react";
import { MicIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { browserRecorder, type Recording, type RecorderLike } from "../voice";

type GetUserMedia = (constraints: MediaStreamConstraints) => Promise<MediaStream>;

function browserGetUserMedia(): GetUserMedia | null {
  if (typeof navigator === "undefined" || typeof navigator.mediaDevices?.getUserMedia !== "function") return null;
  if (typeof MediaRecorder === "undefined") return null;
  return (constraints) => navigator.mediaDevices.getUserMedia(constraints);
}

function reasonOf(error: unknown): string {
  const name = typeof error === "object" && error !== null ? (error as { name?: unknown }).name : undefined;
  if (name === "NotAllowedError" || name === "SecurityError") return "microphone permission denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "no microphone found";
  if (name === "NotReadableError") return "the microphone is in use";
  return error instanceof Error ? error.message : "the microphone could not be opened";
}

const stopTracks = (stream: MediaStream) => stream.getTracks().forEach((t) => t.stop());

export function MicButton(props: {
  onRecorded: (recording: Recording) => void;
  /** The live recorder while recording (for the recording bar), then null. */
  onRecording?: (recorder: RecorderLike | null) => void;
  /** Before the microphone opens: stop a reply being spoken. */
  onStart?: () => void;
  /** A recording too short or silent to send (R3.6). */
  onNothing?: () => void;
  getUserMedia?: GetUserMedia;
  createRecorder?: (stream: MediaStream) => RecorderLike;
}): JSX.Element {
  const getUserMedia = props.getUserMedia ?? browserGetUserMedia();
  const createRecorder = props.createRecorder ?? browserRecorder;
  const [pressed, setPressed] = useState(false);
  const [announce, setAnnounce] = useState("");
  const [unavailable, setUnavailable] = useState<string | null>(
    getUserMedia === null ? "Voice input unavailable: this browser cannot record audio" : null,
  );
  const want = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const recorder = useRef<RecorderLike | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;

  const say = (text: string) => setAnnounce(text);

  const finish = useCallback(async (send: boolean) => {
    if (!want.current) return;
    want.current = false;
    generation.current += 1;
    const live = recorder.current;
    recorder.current = null;
    if (live === null) return; // released before the grant: nothing was recorded, nothing is sent
    setPressed(false);
    callbacks.current.onRecording?.(null);
    if (!send) {
      live.discard();
      return;
    }
    const recording = await live.stop();
    if (!mounted.current) return;
    if (recording === null) {
      say("Nothing recorded");
      callbacks.current.onNothing?.();
      return;
    }
    say("Sent");
    callbacks.current.onRecorded(recording);
  }, []);

  const begin = useCallback(async () => {
    if (want.current || getUserMedia === null) return;
    want.current = true;
    generation.current += 1;
    const asked = generation.current;
    callbacks.current.onStart?.();
    let stream: MediaStream;
    try {
      stream = await getUserMedia({ audio: true });
    } catch (error) {
      if (asked === generation.current && mounted.current) {
        want.current = false;
        const reason = `Voice input unavailable: ${reasonOf(error)}`;
        setUnavailable(reason);
        say(reason);
      }
      return;
    }
    if (!(want.current && asked === generation.current && mounted.current)) {
      stopTracks(stream); // a late grant: released, toggled off or unmounted meanwhile
      return;
    }
    let live: RecorderLike;
    try {
      live = createRecorder(stream);
      live.onCap = () => void finish(true);
      live.start();
    } catch (error) {
      stopTracks(stream); // the recorder failed: the microphone must not stay live
      want.current = false;
      generation.current += 1;
      const reason = `Voice input unavailable: ${reasonOf(error)}`;
      setUnavailable(reason);
      say(reason);
      return;
    }
    recorder.current = live;
    setPressed(true);
    say("Recording");
    callbacks.current.onRecording?.(live);
  }, [createRecorder, finish, getUserMedia]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      want.current = false;
      generation.current += 1;
      recorder.current?.discard();
      recorder.current = null;
    };
  }, []);

  const keyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== " " && e.key !== "Enter") return;
    e.preventDefault();
    if (e.repeat) return;
    if (want.current) void finish(true);
    else void begin();
  };

  return (
    <>
      <Button
        type="button"
        size="icon"
        aria-label="Hold to talk"
        aria-pressed={pressed}
        title={unavailable ?? "Hold to talk (Space or Enter toggles)"}
        disabled={unavailable !== null}
        data-recording={pressed ? "true" : undefined}
        className={cn("mic touch-none select-none", pressed && "mic-recording")}
        onPointerDown={(e) => {
          if (e.button !== 0 && e.pointerType === "mouse") return;
          e.preventDefault();
          void begin();
        }}
        onPointerUp={() => void finish(true)}
        onPointerCancel={() => void finish(true)}
        onPointerLeave={() => void finish(true)}
        onKeyDown={keyDown}
        onKeyUp={(e) => {
          if (e.key === " ") e.preventDefault(); // no click from Space's release
        }}
      >
        <MicIcon />
      </Button>
      <span data-testid="mic-live" aria-live="assertive" className="sr-only">
        {announce}
      </span>
    </>
  );
}

/** The bar above the composer while recording: a level meter and the elapsed time. */
export function RecordingBar(props: { recorder: RecorderLike }): JSX.Element {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 100);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.floor(props.recorder.elapsedMs / 1000);
  const level = Math.min(1, props.recorder.level * 4);
  return (
    <div data-testid="recording" className="flex items-center gap-3 text-sm text-destructive">
      <span className="font-medium">● Recording</span>
      <span className="h-1.5 max-w-56 flex-1 overflow-hidden rounded-full bg-border" aria-hidden="true">
        <span className="block h-full rounded-full bg-destructive transition-[width] duration-100" style={{ width: `${Math.round(level * 100)}%` }} />
      </span>
      <span className="font-mono text-xs text-muted-foreground">{`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</span>
      <span className="hidden text-xs text-muted-foreground sm:inline">release (or press again) to send</span>
    </div>
  );
}
