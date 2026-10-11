---
type: evidence
workItem: issue-23
row: T2, T10
---

# Integration tests (T2) and the upgrade case (T10)

All 56 integration tests pass at `34dccbc` with `TINY_HARNESS_PUSH_KEY` unset, including
the three push-config scenarios and the embedded CLI processes started without the
variable.

```text
$ env -u TINY_HARNESS_PUSH_KEY uv run pytest tests/integration -v
56 passed in 85.93s (0:01:25)
```

## Push-config scenarios

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 5 | A2A server | push notification configs receive status updates | docs/specs/issue-3/requirements.md#R15 (rewritten for issue-23 R2.2, R3.1) | tests/integration/a2a/test_server.py:216 |
| 6 | A2A server | a push config's credentials round-trip through get, list and delete | docs/specs/issue-23/requirements.md#R2 | tests/integration/a2a/test_server.py:287 |
| 7 | A2A server | a push config stored encrypted by an earlier version is dropped, not delivered | docs/specs/issue-23/requirements.md#R4 | tests/integration/a2a/test_server.py:342 |

(`the-loop scenarios --root . --glob tests/integration/a2a/test_server.py --format markdown`,
push rows.)

```text
tests/integration/a2a/test_server.py::test_push_notification_configs_receive_status_updates PASSED
tests/integration/a2a/test_server.py::test_push_config_credentials_round_trip PASSED
tests/integration/a2a/test_server.py::test_legacy_push_config_is_dropped PASSED
tests/integration/embedded/test_cli_embedded.py::test_admin_commands_act_on_persisted_embedded_state PASSED
tests/integration/embedded/test_cli_embedded.py::test_sigterm_to_serve_in_embedded_mode_leaves_no_dev_server PASSED
```

- **Scenario 7 is T10**: a row in the 0.5.x shape (`token_ciphertext` set) is written
  for a live task; listing returns nothing, the completed task posts nothing to the
  row's URL, the row is gone from the store, and the one `WARNING` names the task and
  config id without the ciphertext.
- **The embedded CLI** (`test_sigterm_to_serve_in_embedded_mode_leaves_no_dev_server`,
  `test_admin_commands_act_on_persisted_embedded_state`) starts `tiny-harness serve`
  and the admin commands as subprocesses whose environment has no
  `TINY_HARNESS_PUSH_KEY` (R1.2, R5.3).
- **The worker sandbox** still imports every workflow with `cryptography` gone from its
  pass-through modules: every durable and A2A scenario runs a real worker (R5.4).

## Red before green

With the conftest updated and `push.py` unchanged, the suite could not import
(`cannot import name 'PushTokenCipher'`). After the store rewrite, scenario 7 first
failed with the legacy row listed — the fixture had written it through the new model,
whose ciphertext fields are excluded on write; the fixture now writes the 0.5.x shape
through a test-only subclass, and the scenario passes.
