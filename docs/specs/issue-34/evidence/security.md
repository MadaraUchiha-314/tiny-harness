# T8 — security and abuse-case tests

## `uv run pytest tests/security -q`

```text
83 passed, 125 warnings in 22.90s
```

## `uv run pytest tests/security/test_agent_roster.py -v`

```text
test_instructions_in_a_card_stay_inside_the_untrusted_block PASSED [ 25%]
test_a_card_cannot_close_a_section_or_forge_an_entry PASSED [ 50%]
test_a_huge_card_is_bounded PASSED  [ 75%]
test_an_unregistered_agent_id_is_refused_before_any_request PASSED [100%]
```

| Abuse case (design § Security design) | Test |
|---|---|
| 1 instructions in card text | `test_instructions_in_a_card_stay_inside_the_untrusted_block` |
| 2 tag / newline forgery | `test_a_card_cannot_close_a_section_or_forge_an_entry`; end to end: `tests/integration/agents/test_agents_roster.py::test_a_hostile_agent_card_cannot_break_out_of_the_agents_roster` |
| 3 huge card | `test_a_huge_card_is_bounded` |
| 4 unknown id | `test_an_unregistered_agent_id_is_refused_before_any_request` (a URL, a trailing space, a case change, empty) |
| R1.3 no URL in context | `tests/unit/agents/test_roster.py::test_the_roster_never_reads_the_agent_url`; end to end in `test_the_models_context_lists_a_configured_remote_agent` |

## After R7 (PR review): abuse cases 5–7

`tests/security/test_server_controlled_fields.py`: an untrusted creator's brief setting
`lifecycle`, `model` or `reasoning_effort` is refused whole (5, 6); a trusted delegator's
is accepted; the executor trusts exactly this agent plus `[server] delegators`; an
envelope on an existing task is refused even from an admin (7, unchanged).

`tests/security/test_remote_push.py` and `test_sub_task_flood.py` run on the new route.
The push tests now wait for the stand-in to hear its child park and for the remote's
pushes to stop before measuring: a tiny-harness remote can push one status twice,
seconds apart (both doorbells, harmless). 8 of 8 runs passed after that change.
