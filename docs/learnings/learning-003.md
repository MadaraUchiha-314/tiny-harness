# Learning 003: Provider tool-name constraints belong at the adapter boundary

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-3

## What happened

Registry tool names are `plugin/server.tool`. OpenAI's Responses API rejected the
first live request (`tools[4].name` must match `^[a-zA-Z0-9_-]+$`); Anthropic has the
same rule. The unit tests used `orders.get_order`, which the fixtures accepted because
the recorded responses were hand-written.

## Learning

Names that cross a provider boundary need a reversible mapping built per request,
applied on the way out (tool definitions and history) and decoded on the way back
(tool calls, streamed or not). Renaming entities to fit a provider would couple the
registry to the provider.

## Action

`tiny_harness/harness/models/wire_names.py` with `tests/unit/models/test_wire_names.py`;
the recorded provider fixtures now carry wire names. The capability doc for tools
states the rule.
