import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SpeechItemData } from "../model";
import { SpeechLine, type SpeechUi } from "./SpeechLine";

const item: SpeechItemData = { kind: "speech", url: "http://h/media/t/Sp1", mediaId: "Sp1", state: "streaming", key: "k" };

function show(ui: SpeechUi, over: Partial<SpeechItemData> = {}) {
  const onStop = vi.fn();
  const onReplay = vi.fn();
  render(<SpeechLine item={{ ...item, ...over }} ui={ui} onStop={onStop} onReplay={onReplay} />);
  return { onStop, onReplay };
}

describe("SpeechLine", () => {
  it("while speaking: a marker and Stop", () => {
    const { onStop } = show({ state: "speaking", playedMs: 0 });
    expect(screen.getByRole("status")).toHaveTextContent("Speaking…");
    fireEvent.click(screen.getByRole("button", { name: "Stop speaking" }));
    expect(onStop).toHaveBeenCalled();
  });

  it("once spoken, stopped or interrupted: Replay re-requests", () => {
    for (const [ui, text] of [
      [{ state: "done", playedMs: 7000 }, "Spoken · 0:07"],
      [{ state: "stopped", playedMs: 3000 }, "Stopped at 0:03"],
      [{ state: "interrupted", playedMs: 400 }, "Speech interrupted"],
    ] as const) {
      const { onReplay, onStop } = show(ui);
      expect(screen.getByRole("status")).toHaveTextContent(text);
      fireEvent.click(screen.getByRole("button", { name: "Replay spoken reply" }));
      expect(onReplay).toHaveBeenCalledWith(expect.objectContaining({ mediaId: "Sp1" }));
      expect(onStop).not.toHaveBeenCalled();
      document.body.innerHTML = "";
    }
  });

  it("not played here (another surface, or a replayed log): Play", () => {
    const { onReplay } = show({ state: "idle", playedMs: 0 });
    expect(screen.getByRole("status")).toHaveTextContent("Spoken reply");
    fireEvent.click(screen.getByRole("button", { name: "Play spoken reply" }));
    expect(onReplay).toHaveBeenCalled();
  });

  it("says speech is unavailable when the server could not speak", () => {
    show({ state: "idle", playedMs: 0 }, { state: "failed" });
    expect(screen.getByRole("status")).toHaveTextContent("Speech unavailable");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
