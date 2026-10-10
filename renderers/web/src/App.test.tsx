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
