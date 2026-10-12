import { describe, expect, it } from "vitest";
import {
  COMMANDS_EXT_URI,
  EVENT_MEDIA_TYPE,
  Role,
  STATUS_EXT_KEY,
  TASK_EXT_KEY,
  TaskState,
  commandsOf,
  controlMessage,
  partData,
  textPart,
  type Message,
  type StreamResponse,
} from "./a2a";
import { replay } from "./model";

const TASK = "t-1";
const CTX = "ctx-1";

const task = (state: TaskState, metadata?: Record<string, unknown>): StreamResponse => ({
  payload: {
    $case: "task",
    value: {
      id: TASK,
      contextId: CTX,
      status: { state, message: undefined, timestamp: undefined },
      artifacts: [],
      history: [],
      metadata: { [TASK_EXT_KEY]: { name: "n", goal: "g" }, ...metadata },
    },
  },
});

const agentMessage = (text: string, metadata?: Record<string, string>): Message => ({
  messageId: `m-${text}`,
  contextId: CTX,
  taskId: TASK,
  role: Role.ROLE_AGENT,
  parts: [textPart(text)],
  metadata,
  extensions: [],
  referenceTaskIds: [],
});

const update = (state: TaskState, subState?: string, message?: Message): StreamResponse => ({
  payload: {
    $case: "statusUpdate",
    value: {
      taskId: TASK,
      contextId: CTX,
      status: { state, message, timestamp: undefined },
      metadata: subState === undefined ? undefined : { [STATUS_EXT_KEY]: { sub_state: subState } },
    },
  },
});

describe("the sub-state fold (status extension)", () => {
  it("reads the sub-state from the status update that reports INPUT_REQUIRED", () => {
    const view = replay([task(TaskState.TASK_STATE_WORKING), update(TaskState.TASK_STATE_INPUT_REQUIRED, "awaiting-next-message")]);
    expect(view.state).toBe("INPUT_REQUIRED");
    expect(view.subState).toBe("awaiting-next-message");
    const last = view.items[view.items.length - 1];
    expect(last).toMatchObject({ kind: "status", state: "INPUT_REQUIRED", subState: "awaiting-next-message" });
  });

  it("reads the sub-state from Task.metadata", () => {
    const view = replay([task(TaskState.TASK_STATE_INPUT_REQUIRED, { [STATUS_EXT_KEY]: { sub_state: "awaiting-answer" } })]);
    expect(view.subState).toBe("awaiting-answer");
  });

  it("clears the sub-state when the task leaves INPUT_REQUIRED", () => {
    const view = replay([
      task(TaskState.TASK_STATE_WORKING),
      update(TaskState.TASK_STATE_INPUT_REQUIRED, "awaiting-next-message"),
      update(TaskState.TASK_STATE_WORKING),
    ]);
    expect(view.subState).toBeNull();
  });

  it("treats an unknown sub-state as plain INPUT_REQUIRED", () => {
    const view = replay([task(TaskState.TASK_STATE_WORKING), update(TaskState.TASK_STATE_INPUT_REQUIRED, "awaiting-a-miracle")]);
    expect(view.state).toBe("INPUT_REQUIRED");
    expect(view.subState).toBeNull();
  });

  it("adds a status item when only the sub-state changes", () => {
    const view = replay([
      task(TaskState.TASK_STATE_WORKING),
      update(TaskState.TASK_STATE_INPUT_REQUIRED, "awaiting-answer"),
      update(TaskState.TASK_STATE_INPUT_REQUIRED, "awaiting-next-message"),
    ]);
    expect(view.items.filter((i) => i.kind === "status")).toHaveLength(3);
  });
});

describe("command replies", () => {
  it("folds a re-emitted status update with command metadata into a command item", () => {
    const reply = agentMessage("Starting a sub-task.\nCreated sub-task t-2.", { command: "sub-task", task_ref: "t-2" });
    const view = replay([
      task(TaskState.TASK_STATE_INPUT_REQUIRED, { [STATUS_EXT_KEY]: { sub_state: "awaiting-next-message" } }),
      update(TaskState.TASK_STATE_INPUT_REQUIRED, "awaiting-next-message", reply),
    ]);
    const last = view.items[view.items.length - 1];
    expect(last).toMatchObject({ kind: "command", name: "sub-task", taskRef: "t-2" });
    expect(view.subState).toBe("awaiting-next-message");
  });
});

describe("task snapshots", () => {
  it("do not repeat the status message an update already showed", () => {
    const reply = agentMessage("Noted.");
    const parked = update(TaskState.TASK_STATE_INPUT_REQUIRED, "awaiting-next-message", reply);
    const snapshot = task(TaskState.TASK_STATE_INPUT_REQUIRED, { [STATUS_EXT_KEY]: { sub_state: "awaiting-next-message" } });
    if (snapshot.payload?.$case === "task" && snapshot.payload.value.status) snapshot.payload.value.status.message = reply;
    const view = replay([task(TaskState.TASK_STATE_WORKING), parked, snapshot]);
    expect(view.items.filter((i) => i.kind === "text").map((i) => (i.kind === "text" ? i.text : ""))).toEqual(["Noted."]);
  });
});

describe("the client's harness extensions", () => {
  it("builds the complete control envelope as a data part", () => {
    const message = controlMessage({ taskId: TASK, contextId: CTX, participant: "alice" });
    expect(message.taskId).toBe(TASK);
    expect(message.role).toBe(Role.ROLE_USER);
    expect(message.parts).toHaveLength(1);
    expect(message.parts[0]?.mediaType).toBe(EVENT_MEDIA_TYPE);
    expect(partData(message.parts[0]!)).toEqual({ kind: "control", action: "complete" });
    expect(message.metadata).toEqual({ participant_id: "alice" });
  });

  it("reads the commands from the card's commands extension, in order", () => {
    const card = {
      capabilities: {
        extensions: [
          { uri: "https://example.com/other", description: "", required: false, params: {} },
          {
            uri: COMMANDS_EXT_URI,
            description: "",
            required: false,
            params: {
              commands: [
                { name: "model", description: "Show or choose this task's model", argument_hint: "[<model>]" },
                { name: "status", description: "Show this task's status" },
                { name: 7, description: "malformed" },
              ],
            },
          },
        ],
      },
    };
    expect(commandsOf(card)).toEqual([
      { name: "model", description: "Show or choose this task's model", argument_hint: "[<model>]" },
      { name: "status", description: "Show this task's status", argument_hint: "" },
    ]);
  });

  it("offers no commands when the card has no commands extension", () => {
    expect(commandsOf({ capabilities: { extensions: [] } })).toEqual([]);
    expect(commandsOf({})).toEqual([]);
  });
});
