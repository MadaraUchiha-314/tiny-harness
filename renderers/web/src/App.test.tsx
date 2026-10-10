import { sseEvents } from "./a2a";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { prototypeEvents } from "./fixtures/prototype";
import { replay } from "./model";

describe("the web renderer", () => {
  it("folds the prototype's events into the view", () => {
    const view = replay(prototypeEvents());
    expect(view.state).toBe("INPUT_REQUIRED");
    expect(view.ext?.goal).toContain("damaged-on-arrival");
    expect(view.items.map((i) => i.kind)).toEqual([
      "status",
      "status",
      "text",
      "a2ui",
      "status",
      "help",
      "placeholder",
    ]);
  });

  it("renders the stream, the help request, the placeholder and the task pane", () => {
    render(
      <App
        config={{ baseUrl: "http://test", participant: "you", agent: "support-agent", fixture: prototypeEvents() }}
      />,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("INPUT_REQUIRED");
    expect(screen.getByTestId("help")).toHaveTextContent("two open orders");
    expect(screen.getByTestId("placeholder")).toHaveTextContent("application/vnd.example.calendar+json");
    const task = screen.getByRole("tabpanel", { name: "Task" });
    expect(within(task).getByText(/Resolve the damaged-on-arrival/)).toBeInTheDocument();
    expect(within(task).getByText(/support-agent/)).toBeInTheDocument();
  });
});

function body(text: string, splitAt: number): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      // Two chunks, as a network would deliver them.
      controller.enqueue(bytes.slice(0, splitAt));
      controller.enqueue(bytes.slice(splitAt));
      controller.close();
    },
  });
}

const FRAMES =
  'data: {"task": {"id": "t1", "contextId": "c1", "status": {"state": "TASK_STATE_SUBMITTED"}}}\r\n\r\n' +
  'data: {"statusUpdate": {"taskId": "t1", "contextId": "c1", "status": {"state": "TASK_STATE_WORKING"}}}\r\n\r\n';

async function states(stream: ReadableStream<Uint8Array>): Promise<(string | undefined)[]> {
  const events = [];
  for await (const event of sseEvents(stream)) events.push(event);
  return events.map((e) => (e.task ? e.task.status.state : e.statusUpdate?.status.state));
}

it("sseEvents parses CRLF frames as the a2a-sdk server sends them", async () => {
  expect(await states(body(FRAMES, 40))).toEqual(["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"]);
});

it("sseEvents keeps a CRLF pair whole across a chunk boundary", async () => {
  const firstCr = FRAMES.indexOf("\r");
  expect(await states(body(FRAMES, firstCr + 1))).toEqual(["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"]);
  expect(await states(body(FRAMES, firstCr + 3))).toEqual(["TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"]);
});
