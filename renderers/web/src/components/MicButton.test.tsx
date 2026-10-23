import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Recording, RecorderLike } from "../voice";
import { MicButton } from "./MicButton";

class Track {
  stopped = false;
  stop() {
    this.stopped = true;
  }
}

/** A `getUserMedia` whose grant the test releases (or refuses) when it chooses. */
function deferredMic() {
  const tracks: Track[] = [];
  let grant: (() => void) | null = null;
  let refuse: ((e: Error) => void) | null = null;
  const getUserMedia = vi.fn(
    () =>
      new Promise<MediaStream>((resolve, reject) => {
        const track = new Track();
        tracks.push(track);
        grant = () => resolve({ getTracks: () => [track] } as unknown as MediaStream);
        refuse = reject;
      }),
  );
  return {
    getUserMedia,
    tracks,
    grant: async () => {
      await act(async () => {
        grant?.();
        await Promise.resolve();
      });
    },
    refuse: async (e: Error) => {
      await act(async () => {
        refuse?.(e);
        await Promise.resolve();
      });
    },
  };
}

function fakeRecorders(result: Recording | null = { blob: new Blob(["x"]), mediaType: "audio/webm", durationMs: 1800, filename: "voice.webm" }) {
  const made: Array<RecorderLike & { started: boolean; discarded: boolean; stream: MediaStream }> = [];
  const createRecorder = vi.fn((stream: MediaStream) => {
    const recorder = {
      stream,
      started: false,
      discarded: false,
      level: 0.3,
      elapsedMs: 0,
      onCap: undefined as (() => void) | undefined,
      start() {
        recorder.started = true;
      },
      stop: vi.fn(async () => {
        stream.getTracks().forEach((t) => t.stop());
        return result;
      }),
      discard() {
        recorder.discarded = true;
        stream.getTracks().forEach((t) => t.stop());
      },
      sample() {},
    };
    made.push(recorder);
    return recorder;
  });
  return { createRecorder, made };
}

function setup(result?: Recording | null) {
  const mic = deferredMic();
  const recorders = fakeRecorders(result);
  const onRecorded = vi.fn();
  const onRecording = vi.fn();
  const utils = render(
    <MicButton onRecorded={onRecorded} onRecording={onRecording} getUserMedia={mic.getUserMedia} createRecorder={recorders.createRecorder} />,
  );
  const button = screen.getByRole("button", { name: "Hold to talk" });
  const live = screen.getByTestId("mic-live");
  return { ...utils, ...mic, ...recorders, onRecorded, onRecording, button, live };
}

describe("MicButton", () => {
  it("is a named toggle button with a live region", () => {
    const { button, live } = setup();
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(live).toHaveAttribute("aria-live", "assertive");
  });

  it("records while held: press, the grant, then release sends", async () => {
    const { button, live, grant, onRecorded, made, tracks } = setup();
    fireEvent.pointerDown(button);
    expect(button).toHaveAttribute("aria-pressed", "false"); // nothing records before the grant
    await grant();
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(live).toHaveTextContent("Recording");
    expect(made[0]?.started).toBe(true);
    await act(async () => {
      fireEvent.pointerUp(button);
    });
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(onRecorded).toHaveBeenCalledWith(expect.objectContaining({ mediaType: "audio/webm", durationMs: 1800 }));
    expect(live).toHaveTextContent("Sent");
    expect(tracks.every((t) => t.stopped)).toBe(true);
  });

  it("ends a hold on pointercancel and pointerleave as well", async () => {
    for (const end of ["pointerCancel", "pointerLeave"] as const) {
      const { button, grant, onRecorded, unmount } = setup();
      fireEvent.pointerDown(button);
      await grant();
      await act(async () => {
        fireEvent[end](button);
      });
      expect(onRecorded).toHaveBeenCalledTimes(1);
      unmount();
    }
  });

  it("toggles with Space and Enter from the keyboard, and ignores auto-repeat", async () => {
    for (const key of [" ", "Enter"]) {
      const { button, grant, onRecorded, getUserMedia, unmount } = setup();
      fireEvent.keyDown(button, { key });
      await grant();
      expect(button).toHaveAttribute("aria-pressed", "true");
      fireEvent.keyDown(button, { key, repeat: true });
      expect(button).toHaveAttribute("aria-pressed", "true");
      expect(getUserMedia).toHaveBeenCalledTimes(1);
      await act(async () => {
        fireEvent.keyDown(button, { key });
      });
      expect(button).toHaveAttribute("aria-pressed", "false");
      expect(onRecorded).toHaveBeenCalledTimes(1);
      unmount();
    }
  });

  it("late_grant_stops_tracks: a grant after the release stops the microphone and records nothing", async () => {
    const { button, grant, tracks, createRecorder, onRecorded, live } = setup();
    fireEvent.pointerDown(button);
    fireEvent.pointerUp(button); // released while the permission prompt is still open
    await grant();
    expect(tracks).toHaveLength(1);
    expect(tracks[0]?.stopped).toBe(true);
    expect(createRecorder).not.toHaveBeenCalled();
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(onRecorded).not.toHaveBeenCalled();
    expect(live).not.toHaveTextContent("Recording");
  });

  it("late_grant_stops_tracks: after a keyboard toggle-off, and after an unmount", async () => {
    const toggled = setup();
    fireEvent.keyDown(toggled.button, { key: "Enter" });
    fireEvent.keyDown(toggled.button, { key: "Enter" });
    await toggled.grant();
    expect(toggled.tracks[0]?.stopped).toBe(true);
    expect(toggled.createRecorder).not.toHaveBeenCalled();
    toggled.unmount();

    const gone = setup();
    fireEvent.pointerDown(gone.button);
    gone.unmount();
    await gone.grant();
    expect(gone.tracks[0]?.stopped).toBe(true);
    expect(gone.createRecorder).not.toHaveBeenCalled();
  });

  it("a second press during a pending grant does not open the microphone twice", async () => {
    const { button, grant, getUserMedia, tracks, made } = setup();
    fireEvent.pointerDown(button);
    fireEvent.pointerUp(button);
    fireEvent.pointerDown(button);
    await grant(); // the second request's grant
    expect(getUserMedia).toHaveBeenCalledTimes(2);
    expect(made).toHaveLength(1);
    expect(made[0]?.stream.getTracks()[0]).toBe(tracks[1]);
  });

  it("unmounting while recording discards it and closes the microphone", async () => {
    const { button, grant, made, unmount, tracks } = setup();
    fireEvent.pointerDown(button);
    await grant();
    unmount();
    expect(made[0]?.discarded).toBe(true);
    expect(tracks[0]?.stopped).toBe(true);
  });

  it("says nothing was recorded for a short or silent recording", async () => {
    const { button, grant, onRecorded, live } = setup(null);
    fireEvent.pointerDown(button);
    await grant();
    await act(async () => {
      fireEvent.pointerUp(button);
    });
    expect(onRecorded).not.toHaveBeenCalled();
    expect(live).toHaveTextContent("Nothing recorded");
  });

  it("is disabled with the reason when the microphone is refused", async () => {
    const { button, refuse, live } = setup();
    fireEvent.pointerDown(button);
    await refuse(Object.assign(new Error("Permission denied"), { name: "NotAllowedError" }));
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Voice input unavailable: microphone permission denied");
    expect(live).toHaveTextContent("Voice input unavailable: microphone permission denied");
  });

  it("is disabled with the reason when the browser has no microphone API", () => {
    render(<MicButton onRecorded={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Hold to talk" });
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toMatch(/^Voice input unavailable/);
  });
  it.each([
    ["the recorder cannot be made", "create"],
    ["the recorder cannot start", "start"],
  ])("closes the microphone and names the reason when %s", async (_, where) => {
    const mic = deferredMic();
    const onRecording = vi.fn();
    const createRecorder = vi.fn((): RecorderLike => {
      if (where === "create") throw new Error("MediaRecorder: unsupported MIME type");
      return {
        level: 0,
        elapsedMs: 0,
        start() {
          throw new Error("MediaRecorder: unsupported MIME type");
        },
        stop: async () => null,
        discard() {},
        sample() {},
      };
    });
    render(<MicButton onRecorded={vi.fn()} onRecording={onRecording} getUserMedia={mic.getUserMedia} createRecorder={createRecorder} />);
    const button = screen.getByRole("button", { name: "Hold to talk" });
    fireEvent.pointerDown(button);
    await mic.grant();
    expect(mic.tracks.length).toBe(1);
    expect(mic.tracks.every((t) => t.stopped)).toBe(true);
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Voice input unavailable: MediaRecorder: unsupported MIME type");
    expect(screen.getByTestId("mic-live")).toHaveTextContent("Voice input unavailable: MediaRecorder: unsupported MIME type");
    expect(onRecording).not.toHaveBeenCalledWith(expect.anything());
  });
  it("discards a recorder that cannot start, so its meter's audio context closes", async () => {
    const mic = deferredMic();
    const discard = vi.fn();
    const createRecorder = vi.fn(
      (): RecorderLike => ({
        level: 0,
        elapsedMs: 0,
        start() {
          throw new Error("MediaRecorder: unsupported MIME type");
        },
        stop: async () => null,
        discard,
        sample() {},
      }),
    );
    render(<MicButton onRecorded={vi.fn()} getUserMedia={mic.getUserMedia} createRecorder={createRecorder} />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Hold to talk" }));
    await mic.grant();
    expect(discard).toHaveBeenCalledTimes(1);
    expect(mic.tracks.every((t) => t.stopped)).toBe(true);
  });
});
