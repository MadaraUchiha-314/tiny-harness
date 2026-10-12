import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

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
    expect(onSend).toHaveBeenCalledWith("/status");
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
    expect(onSend).toHaveBeenCalledWith("/xyz");
  });
});
