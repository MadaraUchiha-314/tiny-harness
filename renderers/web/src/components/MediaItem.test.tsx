import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MediaItemData } from "../model";
import { MediaItem } from "./MediaItem";

const item = (over: Partial<MediaItemData>): MediaItemData => ({
  kind: "media",
  role: "user",
  media: "image",
  url: "http://h/media/t/Qm3x",
  name: "room.png",
  mediaType: "image/png",
  mediaId: "Qm3x",
  messageId: null,
  key: "k",
  ...over,
});

describe("MediaItem", () => {
  it("refuses_svg: never fetches or draws an SVG (abuse case 6)", async () => {
    const load = vi.fn(async () => "blob:x/1");
    const { container } = render(<MediaItem item={item({ mediaType: "image/svg+xml", name: "logo.svg" })} load={load} />);
    expect(screen.getByTestId("media-refused")).toHaveTextContent("image/svg+xml");
    await Promise.resolve();
    expect(load).not.toHaveBeenCalled();
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("<svg/>");
  });

  it("refuses HTML and any other type outside the accepted list", () => {
    const load = vi.fn(async () => "blob:x/1");
    render(<MediaItem item={item({ mediaType: "text/html", name: "page.png" })} load={load} />);
    expect(screen.getByTestId("media-refused")).toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
  });

  it("draws an accepted image only from the blob URL, and names the failure when the load is refused", async () => {
    const load = vi.fn(async () => "blob:x/1");
    render(<MediaItem item={item({ size: 1_887_437, width: 2048, height: 1536 })} load={load} />);
    const img = await screen.findByRole("img", { name: "Image room.png" });
    expect(img).toHaveAttribute("src", "blob:x/1");
    expect(load).toHaveBeenCalledWith("http://h/media/t/Qm3x", "image/png");
    expect(screen.getByText("room.png · 1.8 MB · 2048×1536")).toBeInTheDocument();

    const refused = vi.fn(async () => {
      throw new Error("image/svg+xml is not an accepted type");
    });
    render(<MediaItem item={item({ key: "k2", name: "fake.png" })} load={refused} />);
    expect(await screen.findByText(/fake\.png could not be shown/)).toBeInTheDocument();
  });

  it("opens the image full size in a dialog and closes it", async () => {
    render(<MediaItem item={item({})} load={async () => "blob:x/1"} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open room.png full size" }));
    const dialog = screen.getByRole("dialog", { name: "room.png" });
    expect(dialog).toHaveAttribute("open");
    expect(dialog.querySelector("img")).toHaveAttribute("src", "blob:x/1");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(dialog).not.toHaveAttribute("open");
  });

  it("names the agent's image by its alt text", async () => {
    render(<MediaItem item={item({ role: "agent", name: "the room with a green sofa" })} load={async () => "blob:x/2"} />);
    expect(await screen.findByRole("img", { name: "the room with a green sofa" })).toHaveAttribute("src", "blob:x/2");
  });

  it("plays audio from the blob URL and shows the voice turn's transcript", async () => {
    const voice = item({ media: "audio", mediaType: "audio/webm", name: "voice.webm", voice: true, durationMs: 4000 });
    const { container, rerender } = render(<MediaItem item={voice} load={async () => "blob:x/3"} />);
    await waitFor(() => expect(container.querySelector("audio")).toHaveAttribute("src", "blob:x/3"));
    expect(screen.getByText("voice · 0:04")).toBeInTheDocument();
    expect(screen.getByTestId("transcript")).toHaveTextContent("Transcribing…");
    rerender(<MediaItem item={{ ...voice, transcript: "Would a rug work better?" }} load={async () => "blob:x/3"} />);
    expect(screen.getByTestId("transcript")).toHaveTextContent("“Would a rug work better?”");
  });
});
