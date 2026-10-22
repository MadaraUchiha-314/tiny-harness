# T10, T11 — migration and regression

Work item issue-38, activities T10 (0.8.0 compatibility) and T11 (the whole existing
suite). Python 3.14.7, `uv sync --locked --all-extras`, local Temporal dev server.

## T10: `uv run pytest tests/integration/media/test_compat.py -v`

At `ec5f6b8`.

```text
tests/integration/media/test_compat.py::test_a_0_8_0_history_replays_unchanged PASSED
tests/integration/media/test_compat.py::test_a_0_8_0_agent_state_deserialises_unchanged PASSED
2 passed, 51 warnings in 3.02s
exit=0
```

A 0.8.0 workflow history (recorded from `main`) replays on this code, and a stored 0.8.0
`AgentState` and state record deserialise unchanged: `MessageItem.media`, the new
`LLMModelInfo` fields and `IntakeOut.media` are additive with defaults. The card without
`[media]` is identical to 0.8.0's snapshot (`contract.md`). No store migration: media is
a new directory.

## T11: `uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui`

### Run 1 — failed (1 test), at `ec5f6b8`

`env -u TEMPORAL_API_KEY uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui -q -rfE --durations=10`

```text
FAILED tests/ui/test_tui_keys.py::test_voice_a_new_recording_or_message_stops_the_reply[record]
1 failed, 1408 passed, 1692 warnings in 310.86s (0:05:10)
exit=1
```

The failure, trimmed:

```text
________ test_voice_a_new_recording_or_message_stops_the_reply[record] _________
>       async with app.run_test(size=(110, 36)) as pilot:
tests/ui/test_tui_keys.py:911:
.venv/lib/python3.14/site-packages/textual/app.py:2218: in run_test
    raise self._exception
.venv/lib/python3.14/site-packages/textual/timer.py:189: in _tick
    await invoke(self._callback)
tiny_harness/interaction/tui/app.py:1190: in _voice_tick
    self._show_recording()
tiny_harness/interaction/tui/app.py:1216: in _show_recording
    bar = self.query_one("#rec", Static)
E           textual.css.query.NoMatches: No nodes match '#rec' on Screen(id='_default')
```

**Cause:** a real defect, not test flakiness alone. The test presses F5 (a recording
starts) and ends; the TUI's voice timer ticked while the app shut down, with the
recording still open, and drew the recording bar after the screen's widgets were gone.
The same thing can happen to a user who quits while recording, and the microphone stayed
open until the process ended. Run alone, the test failed 1 time in 15.

**Fix:** `22701e9 fix(tui): quitting while recording closes the microphone (issue-38)`,
test first. The new test
`test_voice_quitting_while_recording_closes_the_microphone` failed before the change
(`assert app.recording is None` with `'toggle'`); with only the unmount half of the fix,
its tick-after-shutdown half fails with the same `NoMatches '#rec'`. The app now discards
an open recording and stops speech on unmount, and the voice tick returns once the app
is not running. After the fix, the formerly failing test passed 20 of 20 runs alone.

### Run 2 — passed, at `22701e9`

`env -u TEMPORAL_API_KEY uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui -q -rfE --durations=5 -W ignore::UserWarning`
(`-W ignore::UserWarning` only hides the Temporal pydantic-converter warning in the
summary.)

```text
15 snapshots passed.
============================= slowest 5 durations ==============================
16.38s call     tests/integration/test_package.py::test_the_server_and_the_tui_run_without_the_voice_and_images_extras
11.64s call     tests/security/test_remote_push.py::test_a_forged_terminal_push_is_not_applied
10.53s call     tests/integration/agents/test_remote_updates.py::test_a_fetch_failing_on_the_last_recheck_leaves_the_stand_in_working
9.53s call     tests/integration/mount/test_multi_agent.py::test_five_agents_in_one_app_delegate_to_each_other[starlette]
7.89s call     tests/integration/embedded/test_cli_embedded.py::test_tui_task_controls_against_the_hosted_harness
1410 passed, 1649 warnings in 318.88s (0:05:18)
exit=0
```

1410 = run 1's 1408 passed + the 1 that failed + the 1 test added with the fix. Every
other test is the same as run 1.

### Changes to existing tests

Against the 0.8.0 base (`849a91b`), no existing test was removed or weakened. Existing
test files changed only to add tests or to widen shared fixtures:

| File | Change |
|------|--------|
| `tests/ui/test_tui_keys.py`, `tests/ui/test_tui_snapshots.py`, `tests/ui/prototype.py` | new media and voice tests and fixtures; two import lines replaced |
| `tests/integration/durable/conftest.py` | `Harness(...)` fixture takes optional media store, speech and image providers |
| `tests/integration/mount/conftest.py` | `agent_settings(..., extra="")` for extra TOML sections |
| `tests/integration/a2a/conftest.py` | `make_server(..., media_intake=None)` |
| `tests/integration/streaming_asgi.py` | an app that ends a body early breaks the client read, as a real socket does |
| `tests/e2e/conftest.py` | the multimodal demo needs only `OPENAI_API_KEY`, like the embedded demo |
| `tests/contract/test_agent_card.py`, `test_ext_schemas.py`, `test_intrinsic_schemas.py` | new media card, schema and intrinsic checks |
| `tests/unit/entities/test_ref.py`, `service/test_a2a_units.py`, `service/test_cli.py`, `test_layout.py` | new cases for the media entity kinds, intake, CLI flags and layout |
| `tests/integration/test_package.py` | the extras tests (T12) |
| `tests/contract/snapshots/*` | the additive API and schema changes listed in `contract.md` |

The plan expected the TUI client fixtures to change from `send(text)` to `send(parts)`.
That signature change is in `tiny_harness/interaction/tui/client.py` (the client
protocol, `A2AClient` and the `ScriptedClient` test double); no existing test call site
needed a change, because the TUI app is the only caller.
