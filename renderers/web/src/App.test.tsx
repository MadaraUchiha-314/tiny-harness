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

function body(text: string): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      // Two chunks, split inside the second frame, as a network would deliver it.
      controller.enqueue(bytes.slice(0, 40));
      controller.enqueue(bytes.slice(40));
      controller.close();
    },
  });
}

it("sseEvents parses CRLF frames as the a2a-sdk server sends them", async () => {
  const frames =
    'data: {"task": {"id": "t1", "contextId": "c1", "status": {"state": "TASK_STATE_SUBMITTED"}}}\r\n\r\n' +
    'data: {"statusUpdate": {"taskId": "t1", "contextId": "c1", "status": {"state": "TASK_STATE_WORKING"}}}\r\n\r\n';
  const events = [];
  for await (const event of sseEvents(body(frames))) events.push(event);
  expect(events.map((e) => (e.task ? e.task.status.state : e.statusUpdate?.status.state))).toEqual([
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
  ]);
});
