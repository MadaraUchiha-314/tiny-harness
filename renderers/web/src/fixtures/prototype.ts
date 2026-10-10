/** The A2A events behind the first state of `design/web-renderer.html`. */
import { A2UI_MEDIA_TYPE, CHANNEL_MEDIA_TYPE, TASK_EXT_KEY, type JsonObject, type StreamResponse } from "../a2a";

export const TASK_ID = "7f3a0000-0000-0000-0000-00000000c21e";
export const CONTEXT_ID = "ctx-7f3a";
const CATALOG = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json";

const extension: JsonObject = {
  name: "Refund order #48213",
  goal: "Resolve the damaged-on-arrival complaint on order #48213 within policy.",
  description: "",
  acceptance_criteria: [
    { text: "Order and warranty verified", met: true },
    { text: "Policy applied and cited", met: true },
    { text: "Customer offered a resolution they accept", met: false },
    { text: "Ticket closed with the resolution recorded", met: false },
  ],
  participants: [
    { id: "support-agent", kind: "agent", role: "assignee", display_name: "" },
    { id: "you", kind: "human", role: "reporter", display_name: "" },
    { id: "billing-agent", kind: "agent", role: "watcher", display_name: "" },
    { id: "ops-lead", kind: "human", role: "admin", display_name: "" },
  ],
  parent_tasks: [],
  sub_tasks: [{ task_id: "t-91a0", agent: { kind: "agent", id: "billing-agent", version: null } }],
  plan: {
    steps: [
      { id: "verify", name: "Verify order and delivery", description: "", depends_on: [], output: "delivered 2026-10-06, warranty active", linked_tasks: [], state: "done" },
      { id: "policy", name: "Look up damage policy", description: "", depends_on: ["verify"], output: "refund or replacement, photo over $75", linked_tasks: [], state: "done" },
      { id: "agree", name: "Agree resolution with customer", description: "", depends_on: ["policy"], output: null, linked_tasks: [{ task_id: "t-91a0", agent: { kind: "agent", id: "billing-agent", version: null } }], state: "active" },
      { id: "close", name: "Record resolution and close", description: "", depends_on: ["agree"], output: null, linked_tasks: [], state: "pending" },
    ],
  },
};

export const CARD: JsonObject = {
  version: "v0.9.1",
  updateComponents: {
    surfaceId: "resolution",
    components: [
      { id: "root", component: "Card", child: "col" },
      { id: "col", component: "Column", children: ["title", "pick", "ok"] },
      { id: "title", component: "Text", text: "Proposed resolution" },
      {
        id: "pick",
        component: "ChoicePicker",
        label: "Resolution",
        options: [
          { label: "Ship replacement now", value: "replace" },
          { label: "Refund after photo", value: "refund" },
          { label: "Escalate to a human", value: "escalate" },
        ],
        value: { path: "/choice" },
      },
      {
        id: "ok",
        component: "Button",
        child: "ok-label",
        action: { event: { name: "confirm", context: { choice: { path: "/choice" } } } },
      },
      { id: "ok-label", component: "Text", text: "Confirm" },
    ],
  },
};

export function prototypeEvents(): StreamResponse[] {
  const status = (state: string) => ({ taskId: TASK_ID, contextId: CONTEXT_ID, status: { state } });
  return [
    {
      task: {
        id: TASK_ID,
        contextId: CONTEXT_ID,
        status: { state: "TASK_STATE_SUBMITTED" },
        metadata: { [TASK_EXT_KEY]: extension },
      },
    },
    { statusUpdate: status("TASK_STATE_WORKING") },
    {
      statusUpdate: {
        ...status("TASK_STATE_WORKING"),
        status: {
          state: "TASK_STATE_WORKING",
          message: {
            messageId: "m-agent-1",
            role: "ROLE_AGENT",
            parts: [
              {
                text:
                  "The order qualifies for a damaged-on-arrival resolution. The item is $129, so policy " +
                  "needs a photo before a refund. A replacement can ship without one.",
              },
            ],
          },
        },
      },
    },
    {
      artifactUpdate: {
        taskId: TASK_ID,
        contextId: CONTEXT_ID,
        artifact: {
          artifactId: "a2ui:1",
          name: "a2ui",
          parts: [
            { data: { version: "v0.9.1", createSurface: { surfaceId: "resolution", catalogId: CATALOG } }, mediaType: A2UI_MEDIA_TYPE },
            { data: CARD, mediaType: A2UI_MEDIA_TYPE },
          ],
        },
        lastChunk: true,
      },
    },
    {
      statusUpdate: {
        ...status("TASK_STATE_INPUT_REQUIRED"),
        status: {
          state: "TASK_STATE_INPUT_REQUIRED",
          message: {
            messageId: "help-1",
            role: "ROLE_AGENT",
            parts: [
              {
                text:
                  "The customer has two open orders. Should the replacement go to the address on " +
                  "order #48213 or the newer address on #48377? I need a judgement call before I can continue.",
              },
              {
                data: { channel_id: TASK_ID, sender: "support-agent", kind: "help_request", text: "", parts: [], in_reply_to: null },
                mediaType: CHANNEL_MEDIA_TYPE,
              },
            ],
          },
        },
      },
    },
    {
      artifactUpdate: {
        taskId: TASK_ID,
        contextId: CONTEXT_ID,
        artifact: {
          artifactId: "cal-1",
          name: "calendar",
          parts: [{ data: { when: "2026-10-10" }, mediaType: "application/vnd.example.calendar+json" }],
        },
        lastChunk: true,
      },
    },
  ];
}
