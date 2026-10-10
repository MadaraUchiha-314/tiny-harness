# A2A extensions

tiny-harness is an [A2A 1.0](https://a2a-protocol.org/) agent. Its agent card advertises
three extensions; a client activates them with the `A2A-Extensions` header, and a request
naming an extension the card does not list is refused with the unsupported-operation
error.

| URI | What it adds |
|-----|--------------|
| [`…/a2a/ext/task/v1`](ext/task/v1) | the task attributes A2A lacks (name, goal, acceptance criteria, participants, plan, sub-task links) in `Task.metadata`, and the event envelope as data parts |
| [`…/a2a/ext/channel/v1`](ext/channel/v1) | channels between participants: messages, help requests and help replies as data parts |
| `https://a2ui.org/a2a-extension/a2ui/v0.9.1` | [A2UI 0.9.1](https://a2ui.org/) surfaces streamed as `application/a2ui+json` artifact parts, and user actions sent back as the same media type; only the basic catalog, no inline catalogs |

The full URIs are rooted at `https://madarauchiha-314.github.io/tiny-harness`. The JSON
schemas are committed under `docs/a2a/ext/` and the agent card is pinned by a contract
test (`tests/contract/test_agent_card.py`).
