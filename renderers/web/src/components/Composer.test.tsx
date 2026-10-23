import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Composer, type Attachment } from "./Composer";
import type { MediaParams } from "../media";

const COMMANDS = [
  { name: "model", description: "Show or choose this task's model", argument_hint: "[<model>]" },
  { name: "effort", description: "Show or set this task's reasoning effort", argument_hint: "[low|medium|high]" },
  { name: "sub-task", description: "Start a linked sub-task", argument_hint: "<description>" },
  { name: "status", description: "Show this task's status", argument_hint: "" },
];

function setup() {
  const onSend = vi.fn();
  render(<Composer onSend={onSend} disabled={false} commands={COMMANDS} />);
  const box = screen.getByRole("combobox", { name: "Message or /command" });
  const type = (value: string) => fireEvent.change(box, { target: { value } });
  const key = (k: string) => fireEvent.keyDown(box, { key: k });
  return { box, onSend, type, key };
}

describe("the composer's command listbox (WAI-ARIA combobox)", () => {
  it("is closed until the text starts with /", () => {
    const { box, type } = setup();
    expect(box).toHaveAttribute("aria-expanded", "false");
    type("hello");
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("lists every command in registration order on /", () => {
    const { box, type } = setup();
    type("/");
    expect(box).toHaveAttribute("aria-expanded", "true");
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "/model [<model>]Show or choose this task's model",
      "/effort [low|medium|high]Show or set this task's reasoning effort",
      "/sub-task <description>Start a linked sub-task",
      "/statusShow this task's status",
    ]);
    expect(box).toHaveAttribute("aria-activedescendant", "cmd-model");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
  });

  it("filters by prefix and closes once an argument starts", () => {
    const { box, type } = setup();
    type("/s");
    expect(screen.getAllByRole("option").map((o) => o.id)).toEqual(["cmd-sub-task", "cmd-status"]);
    type("/sub-task Draft");
    expect(box).toHaveAttribute("aria-expanded", "false");
  });

  it("moves with Up and Down, and Enter accepts without sending", () => {
    const { box, onSend, type, key } = setup();
    type("/");
    key("ArrowDown");
    expect(box).toHaveAttribute("aria-activedescendant", "cmd-effort");
    key("ArrowUp");
    key("ArrowUp");
    expect(box).toHaveAttribute("aria-activedescendant", "cmd-status");
    key("Enter");
    expect(box).toHaveValue("/status ");
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(onSend).not.toHaveBeenCalled();
    key("Enter");
    expect(onSend).toHaveBeenCalledWith("/status", []);
  });

  it("accepts with Tab and closes with Escape", () => {
    const { box, type, key } = setup();
    type("/e");
    key("Tab");
    expect(box).toHaveValue("/effort ");
    type("/");
    key("Escape");
    expect(box).toHaveAttribute("aria-expanded", "false");
    expect(box).toHaveValue("/");
  });

  it("accepts an option by pointer", () => {
    const { box, type } = setup();
    type("/");
    fireEvent.mouseDown(screen.getByRole("option", { name: /sub-task/ }));
    expect(box).toHaveValue("/sub-task ");
  });

  it("sends an unregistered /x as typed", () => {
    const { onSend, type, key } = setup();
    type("/xyz");
    key("Enter");
    expect(onSend).toHaveBeenCalledWith("/xyz", []);
  });
});

// --- issue-38: attachments ------------------------------------------------------------

const MEDIA: MediaParams = {
  input: ["image/png", "image/jpeg", "audio/wav", "audio/webm"],
  output: [],
  maxFileBytes: 20 * 1024 * 1024,
  maxMessageBytes: 25 * 1024 * 1024,
  maxAudioSeconds: 120,
  speechToText: true,
  textToSpeech: false,
  imageGeneration: false,
  mediaPath: "/media",
};
const ATTACH = { name: "attach", description: "Attach a local image or audio file", argument_hint: "<path>", runsOn: "surface" as const };

const file = (name: string, type: string, size = 4) => new File([new Uint8Array(size)], name, { type });

function setupMedia(onSend: (text: string, files: Attachment[]) => void | Promise<boolean> = vi.fn()) {
  const onError = vi.fn();
  const utils = render(<Composer onSend={onSend} disabled={false} commands={[...COMMANDS, ATTACH]} media={MEDIA} onError={onError} />);
  const input = utils.container.querySelector<HTMLInputElement>("input[type=file]")!;
  const box = screen.getByRole("combobox", { name: "Message or /command" });
  return { ...utils, input, box, onError, onSend };
}

describe("the composer's attachments", () => {
  it("has a paperclip that opens a hidden multi-file picker limited to the card's types", () => {
    const { input } = setupMedia();
    expect(input).toHaveAttribute("multiple");
    expect(input).toHaveAttribute("accept", "image/png,image/jpeg,audio/wav,audio/webm");
    expect(input).toHaveClass("sr-only");
    expect(input).toHaveAttribute("tabindex", "-1");
    const click = vi.spyOn(input, "click");
    fireEvent.click(screen.getByRole("button", { name: "Attach image or audio" }));
    expect(click).toHaveBeenCalled();
  });

  it("hides the paperclip when the card has no media extension", () => {
    render(<Composer onSend={vi.fn()} disabled={false} commands={COMMANDS} />);
    expect(screen.queryByRole("button", { name: "Attach image or audio" })).toBeNull();
  });

  it("shows a chip per picked file and removes one with ×", () => {
    const { input } = setupMedia();
    fireEvent.change(input, { target: { files: [file("room.png", "image/png", 2048), file("note.wav", "audio/wav")] } });
    const chips = screen.getByRole("list", { name: "Attachments" });
    expect(chips).toHaveTextContent("room.png · 2 KB");
    expect(chips).toHaveTextContent("note.wav · 4 B");
    fireEvent.click(screen.getByRole("button", { name: "Remove room.png" }));
    expect(chips).not.toHaveTextContent("room.png");
  });

  it("refuses a file the card does not accept, with the reason, and adds no chip", () => {
    const { input, onError } = setupMedia();
    fireEvent.change(input, { target: { files: [file("logo.svg", "image/svg+xml")] } });
    expect(onError).toHaveBeenCalledWith("Not attached: logo.svg is not a file this agent accepts.");
    expect(screen.queryByRole("button", { name: "Remove logo.svg" })).toBeNull();
  });

  it("takes files dropped on the form and image files pasted into the box", () => {
    const { container, box } = setupMedia();
    const form = container.querySelector("form")!;
    fireEvent.dragOver(form, { dataTransfer: { files: [], types: ["Files"] } });
    expect(form).toHaveAttribute("data-drop", "true");
    fireEvent.drop(form, { dataTransfer: { files: [file("drop.png", "image/png")], types: ["Files"] } });
    expect(form).not.toHaveAttribute("data-drop");
    fireEvent.paste(box, { clipboardData: { files: [file("paste.png", "image/png")], types: ["Files"] } });
    const chips = screen.getByRole("list", { name: "Attachments" });
    expect(chips).toHaveTextContent("drop.png");
    expect(chips).toHaveTextContent("paste.png");
  });

  it("sends the text and the files, then clears both", () => {
    const { input, box, onSend } = setupMedia();
    fireEvent.change(input, { target: { files: [file("room.png", "image/png")] } });
    fireEvent.change(box, { target: { value: "warmer?" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
    const [text, files] = (onSend as ReturnType<typeof vi.fn>).mock.calls[0] as [string, Attachment[]];
    expect(text).toBe("warmer?");
    expect(files.map((f) => [f.name, f.mediaType, f.kind])).toEqual([["room.png", "image/png", "image"]]);
    expect(box).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Remove room.png" })).toBeNull();
  });

  it("sends files without text", () => {
    const { input, onSend } = setupMedia();
    fireEvent.change(input, { target: { files: [file("room.png", "image/png")] } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledWith("", expect.any(Array));
  });

  it("puts the chips and the text back when the server refuses the message", async () => {
    const { input, box } = setupMedia(async () => false);
    fireEvent.change(input, { target: { files: [file("photo.png", "image/png")] } });
    fireEvent.change(box, { target: { value: "look" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "Remove photo.png" })).toBeInTheDocument();
    expect(box).toHaveValue("look");
  });

  it("runs /attach locally: it opens the picker and sends nothing", () => {
    const { input, box, onSend } = setupMedia();
    const click = vi.spyOn(input, "click");
    fireEvent.change(box, { target: { value: "/attach" } });
    fireEvent.keyDown(box, { key: "Escape" });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(click).toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
    expect(box).toHaveValue("");
  });

  it("sends /attach as text when the card does not list it as a surface command", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} commands={COMMANDS} media={MEDIA} />);
    const box = screen.getByRole("combobox", { name: "Message or /command" });
    fireEvent.change(box, { target: { value: "/attach x" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("/attach x", []);
  });
});
