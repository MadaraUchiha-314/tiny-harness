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
