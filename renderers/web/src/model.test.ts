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
  type Part,
  type StreamResponse,
} from "./a2a";
import { replay, withoutMessage } from "./model";

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

// --- issue-38: media and speech items -------------------------------------------------

const PNG = "image/png";
const PCM = "audio/L16;rate=24000;channels=1";
const urlPart = (url: string, mediaType: string, filename: string, metadata?: Record<string, unknown>): Part => ({
  content: { $case: "url", value: url },
  metadata,
  filename,
  mediaType,
});
const artifactEvent = (artifactId: string, name: string, parts: Part[], metadata?: Record<string, unknown>): StreamResponse => ({
  payload: {
    $case: "artifactUpdate",
    value: {
      taskId: TASK,
      contextId: CTX,
      artifact: { artifactId, name, description: "", parts, metadata, extensions: [] },
      append: false,
      lastChunk: true,
      metadata: undefined,
    },
  },
});
const userWith = (messageId: string, parts: Part[]): StreamResponse => ({
  payload: {
    $case: "message",
    value: { messageId, contextId: CTX, taskId: TASK, role: Role.ROLE_USER, parts, metadata: undefined, extensions: [], referenceTaskIds: [] },
  },
});
const URL_A = "http://h/media/t-1/Qm3xAAAA";
const URL_V = "http://h/media/t-1/VoiceBBB";

describe("media items (issue-38)", () => {
  it("turns an accepted url file part into a media item, and an SVG into a placeholder", () => {
    const message: Message = {
      ...agentMessage("look"),
      parts: [urlPart(URL_A, PNG, "room.png", { mediaId: "Qm3xAAAA", size: 1024 }), urlPart("http://h/x.svg", "image/svg+xml", "x.svg")],
    };
    const view = replay([task(TaskState.TASK_STATE_WORKING), update(TaskState.TASK_STATE_INPUT_REQUIRED, undefined, message)]);
    const media = view.items.filter((i) => i.kind === "media");
    expect(media).toEqual([
      expect.objectContaining({ kind: "media", role: "agent", media: "image", url: URL_A, name: "room.png", mediaType: PNG, mediaId: "Qm3xAAAA", size: 1024 }),
    ]);
    expect(view.items.find((i) => i.kind === "placeholder")).toMatchObject({ mediaType: "image/svg+xml" });
  });

  it("binds the echo of the user's own message to the items already shown, without repeating them", () => {
    const local = userWith("msg-1", [urlPart("local:1", PNG, "room.png"), textPart("warmer?")]);
    const echo = artifactEvent("message:msg-1", "user message", [textPart("warmer?"), urlPart(URL_A, PNG, "room.png", { mediaId: "Qm3xAAAA", size: 2048 })], {
      role: "user",
      participant_id: "you",
      message_id: "msg-1",
    });
    const view = replay([local, echo]);
    expect(view.items.map((i) => i.kind)).toEqual(["media", "text"]);
    expect(view.items[0]).toMatchObject({ url: URL_A, mediaId: "Qm3xAAAA", size: 2048, role: "user" });
  });

  it("shows the echo of another participant's message as their media and text", () => {
    const echo = artifactEvent("message:msg-9", "user message", [textPart("and this?"), urlPart(URL_A, PNG, "sofa.png", { mediaId: "Qm3xAAAA" })], {
      role: "user",
      participant_id: "bob",
      message_id: "msg-9",
    });
    const view = replay([task(TaskState.TASK_STATE_WORKING), echo]);
    const shown = view.items.filter((i) => i.kind !== "status");
    expect(shown.map((i) => i.kind)).toEqual(["media", "text"]);
    expect(shown[0]).toMatchObject({ role: "user", name: "sofa.png", url: URL_A });
    expect(shown[1]).toMatchObject({ role: "user", text: "and this?" });
  });

  it("attaches a transcript to its voice item, whichever comes first", () => {
    const voice = urlPart(URL_V, "audio/webm", "voice.webm", { mediaId: "VoiceBBB", voice: true, durationMs: 4000 });
    const echo = artifactEvent("message:msg-2", "user message", [voice], { role: "user", participant_id: "you", message_id: "msg-2" });
    const transcript = artifactEvent("transcript:VoiceBBB", "transcript", [textPart("Would a rug work better?")], { mediaId: "VoiceBBB" });
    for (const events of [[echo, transcript], [transcript, echo]]) {
      const view = replay(events);
      const items = view.items.filter((i) => i.kind !== "status");
      expect(items).toHaveLength(1);
      expect(items[0]).toMatchObject({ kind: "media", media: "audio", voice: true, durationMs: 4000, transcript: "Would a rug work better?" });
    }
  });

  it("shows the agent's image named by its alt text", () => {
    const image = artifactEvent("image:Img1", "the room with a green sofa", [urlPart(URL_A, PNG, "image.png", { mediaId: "Img1" })], { mediaId: "Img1" });
    const view = replay([image]);
    expect(view.items).toEqual([
      expect.objectContaining({ kind: "media", role: "agent", media: "image", name: "the room with a green sofa", url: URL_A, mediaId: "Img1" }),
    ]);
  });

  it("places a spoken reply under the reply's text, and marks it failed on 'speech unavailable'", () => {
    const speech = artifactEvent("speech:Sp1", "speech", [urlPart("http://h/media/t-1/Sp1", PCM, "", { mediaId: "Sp1" })], { mediaId: "Sp1" });
    const view = replay([
      task(TaskState.TASK_STATE_WORKING),
      speech,
      update(TaskState.TASK_STATE_INPUT_REQUIRED, undefined, agentMessage("Yes, a rug.")),
    ]);
    const kinds = view.items.map((i) => i.kind);
    expect(kinds.indexOf("speech")).toBe(kinds.indexOf("text") + 1);
    expect(view.items.find((i) => i.kind === "speech")).toMatchObject({ url: "http://h/media/t-1/Sp1", mediaId: "Sp1", state: "streaming" });
    const failed = replay([
      task(TaskState.TASK_STATE_WORKING),
      speech,
      update(TaskState.TASK_STATE_INPUT_REQUIRED, undefined, agentMessage("Yes, a rug.")),
      update(TaskState.TASK_STATE_INPUT_REQUIRED, undefined, agentMessage("speech unavailable")),
    ]);
    expect(failed.items.find((i) => i.kind === "speech")).toMatchObject({ state: "failed" });
  });

  it("drops the user's own items of a message the server refused", () => {
    const local = userWith("msg-3", [urlPart("local:1", PNG, "photo.png"), textPart("hi")]);
    const view = withoutMessage(replay([local]), "msg-3");
    expect(view.items).toEqual([]);
  });
});
