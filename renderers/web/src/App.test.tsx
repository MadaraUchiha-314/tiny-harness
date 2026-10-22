import { Role, userMessage } from "./a2a";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { CONTROLS_ROOT, FixtureClient } from "./fixtures/controls";
import { prototypeEvents } from "./fixtures/prototype";
import { MEDIA_ROOT, MediaFixtureClient } from "./fixtures/media";
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

  it("shows the sub-state badge and enables Complete and Cancel while INPUT_REQUIRED", () => {
    render(<App config={{ baseUrl: "http://test", participant: "you", agent: "a", fixture: prototypeEvents() }} />);
    expect(screen.getByTestId("sub-state")).toHaveTextContent("awaiting answer");
    const controls = screen.getByRole("group", { name: "Task controls" });
    expect(within(controls).getByRole("button", { name: "Complete" })).toBeEnabled();
    expect(within(controls).getByRole("button", { name: "Cancel task" })).toBeEnabled();
  });

  it("links each sub-task to ?task=<id>", () => {
    render(<App config={{ baseUrl: "http://test", participant: "you", agent: "a", fixture: prototypeEvents() }} />);
    const task = screen.getByRole("tabpanel", { name: "Task" });
    expect(within(task).getByRole("link", { name: "t-91a0" })).toHaveAttribute("href", "?task=t-91a0");
  });

  it("disables Complete and Cancel while no task is open", () => {
    render(<App config={{ baseUrl: "http://test", participant: "you", agent: "a" }} />);
    expect(screen.getByRole("button", { name: "Complete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel task" })).toBeDisabled();
    expect(screen.queryByTestId("sub-state")).toBeNull();
  });
});

describe("task controls against the harness (fixture client)", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  const mount = () =>
    render(
      <App
        config={{ baseUrl: "http://test", participant: "you", agent: "a", taskId: CONTROLS_ROOT, client: new FixtureClient() }}
      />,
    );

  const send = async (text: string) => {
    const box = screen.getByRole("combobox", { name: "Message or /command" });
    fireEvent.change(box, { target: { value: text } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
  };

  it("attaches to the task and offers the card's commands", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("sub-state")).toHaveTextContent("awaiting next message"));
    expect(screen.getByTestId("state")).toHaveTextContent("INPUT_REQUIRED");
    // The snapshot only names the task; the replayed log shows the reply once, in order.
    expect(screen.getAllByText(/#48213 \(damaged blender\)/)).toHaveLength(1);
    expect(screen.getAllByTestId("status").map((s) => s.textContent)).toEqual([
      "task → WORKING",
      "task → INPUT_REQUIRED · awaiting next message",
    ]);
    const box = screen.getByRole("combobox", { name: "Message or /command" });
    fireEvent.change(box, { target: { value: "/" } });
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(4));
    expect(screen.getAllByRole("option").map((o) => o.id)).toEqual(["cmd-model", "cmd-effort", "cmd-sub-task", "cmd-status"]);
  });

  it("walks reply → /sub-task → open → back → Complete", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("INPUT_REQUIRED"));

    await send("/sub-task Draft the reply");
    const reply = await screen.findByTestId("command");
    expect(reply).toHaveTextContent("/sub-task");
    expect(reply).toHaveTextContent(/Created sub-task/);
    const pane = screen.getByRole("tabpanel", { name: "Task" });
    const link = await within(pane).findByRole("link", { name: /^5b1d/ });

    // Completing the parent while the sub-task is open is refused by the harness.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    });
    await waitFor(() => expect(screen.getByText(/completion refused: unresolved sub-tasks/)).toBeInTheDocument());
    expect(screen.getByTestId("state")).toHaveTextContent("INPUT_REQUIRED");

    // Open the sub-task in place, then complete it.
    await act(async () => {
      fireEvent.click(link);
    });
    await waitFor(() => expect(screen.getByTestId("parent")).toBeInTheDocument());
    expect(window.location.search).toContain("task=5b1d");
    await waitFor(() => expect(screen.getByTestId("sub-state")).toHaveTextContent("awaiting next message"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("COMPLETED"));
    expect(screen.queryByTestId("sub-state")).toBeNull();
    expect(screen.getByRole("button", { name: "Complete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel task" })).toBeDisabled();

    // Back to the parent and complete it.
    await act(async () => {
      fireEvent.click(screen.getByTestId("parent"));
    });
    await waitFor(() => expect(screen.queryByTestId("parent")).toBeNull());
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("INPUT_REQUIRED"));
    expect(window.location.search).toContain(`task=${CONTROLS_ROOT}`);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("COMPLETED"));
    expect(screen.getByText("completed by you")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Complete" })).toBeDisabled();
  });

  it("shows the harness's refusal of a message to a terminal task", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("INPUT_REQUIRED"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel task" }));
    });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("CANCELED"));
    await send("anything else?");
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("the task is in a terminal state (TASK_STATE_CANCELED)"),
    );
  });
});

it("userMessage builds the SDK's message shape with the participant in the metadata", () => {
  const message = userMessage({ text: "hello", contextId: "ctx-1", taskId: "t-1", participant: "alice" });
  expect(message.role).toBe(Role.ROLE_USER);
  expect(message.taskId).toBe("t-1");
  expect(message.parts[0]?.content).toEqual({ $case: "text", value: "hello" });
  expect(message.metadata).toEqual({ participant_id: "alice" });
});

describe("media against the harness (issue-38 fixture client)", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    let n = 0;
    Object.assign(URL, { createObjectURL: () => `blob:test/${(n += 1)}`, revokeObjectURL: () => undefined });
  });

  const mount = () =>
    render(
      <App config={{ baseUrl: "http://test", participant: "you", agent: "a", taskId: MEDIA_ROOT, client: new MediaFixtureClient() }} />,
    );

  it("shows the conversation's images, voice turn, transcript and the agent's image", async () => {
    mount();
    expect(await screen.findByRole("img", { name: "Image living-room.png" })).toHaveAttribute("src", expect.stringMatching(/^blob:/));
    expect(await screen.findByText("“Would a rug work better than a throw on the sofa in the first photo?”")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Generated: the same room with a green sofa and a rust rug" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attach image or audio" })).toBeInTheDocument();
  });

  it("puts the chips back and names the file when the harness refuses it", async () => {
    const { container } = mount();
    await screen.findByRole("img", { name: "Image living-room.png" });
    const input = container.querySelector<HTMLInputElement>("input[type=file]")!;
    fireEvent.change(input, { target: { files: [new File([new Uint8Array([1, 2, 3])], "photo.png", { type: "image/png" })] } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    await waitFor(() =>
      expect(screen.getByTestId("error")).toHaveTextContent("Not sent: photo.png is not a file this agent accepts. Remove it and send again."),
    );
    expect(screen.getByRole("button", { name: "Remove photo.png" })).toBeInTheDocument();
  });
});

describe("voice controls against the harness (issue-38 fixture client)", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    let n = 0;
    Object.assign(URL, { createObjectURL: () => `blob:test/${(n += 1)}`, revokeObjectURL: () => undefined });
  });

  it("asks for a spoken reply while the speaker is on, and not once it is off", async () => {
    const client = new MediaFixtureClient();
    const sent: Array<unknown> = [];
    const original = client.sendMessage.bind(client);
    client.sendMessage = (message) => {
      sent.push(message.metadata?.["speak"]);
      return original(message);
    };
    render(<App config={{ baseUrl: "http://test", participant: "you", agent: "a", taskId: MEDIA_ROOT, client }} />);
    const speaker = await screen.findByRole("button", { name: "Spoken replies" });
    expect(speaker).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Hold to talk" })).toBeInTheDocument();
    const box = screen.getByRole("combobox", { name: "Message or /command" });
    fireEvent.change(box, { target: { value: "first" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    await waitFor(() => expect(screen.getAllByTestId("speech").length).toBeGreaterThan(1));
    fireEvent.click(speaker);
    expect(speaker).toHaveAttribute("aria-pressed", "false");
    fireEvent.change(box, { target: { value: "second" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    expect(sent).toEqual([true, false]);
  });

  it("shows no mic or speaker for a harness without the media extension", async () => {
    render(<App config={{ baseUrl: "http://test", participant: "you", agent: "a", taskId: CONTROLS_ROOT, client: new FixtureClient() }} />);
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("INPUT_REQUIRED"));
    expect(screen.queryByRole("button", { name: "Hold to talk" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Spoken replies" })).toBeNull();
  });
});
