# Manual exploratory walkthrough — T11

The procedure for the owner, to be performed on their machine with the keyring secrets
and annotated below. The loop cannot tick T11 on the owner's behalf; it stays unticked
until the owner's notes are recorded here.

## Procedure

1. Bring-up, as in the [getting started](../../../guide/getting-started.md) guide:
   export the three variables (`TEMPORAL_API_KEY`, `OPENAI_API_KEY` from the keyring,
   `TINY_HARNESS_PUSH_KEY` generated), build the web renderer, run
   `uv run python -m examples.demo`, and open `http://127.0.0.1:8080/ui/` and
   `uv run tiny-harness tui --url http://127.0.0.1:8080` side by side.
2. In the web renderer, send: *Refund order #48213: the customer says the blender arrived
   cracked. Check the order and propose a resolution.* Watch SUBMITTED, WORKING, the A2UI
   card and the INPUT_REQUIRED question arrive. Check the Task and Plan tabs.
3. In the TUI, open the same task (`tiny-harness tui` subscribes by task id; or send a
   second message from the TUI with the same context) and confirm both surfaces show the
   same events.
4. Pick an option on the card and press the button in one surface; answer the follow-up
   question in text in the other. Expect COMPLETED with a two-sentence summary and the
   `ship_replacement` or `refund` call in `examples/demo/.state/plugin-data/demo-support/orders-ledger.jsonl`.
5. Open the Temporal Cloud UI for namespace `tiny-harness.gtebu` and find the task's
   workflow: every `invoke_llm` and `invoke_tool` activity, and the `inbox` update.
6. Try an abuse: send a message as a participant who is not on the task (another
   `?participant=` in the web renderer) and expect the refusal status update.
7. Tear-down: stop the process; `uv run tiny-harness --config examples/demo/config.toml schedules delete`.

## Owner's notes

*Not yet performed by the owner.*
