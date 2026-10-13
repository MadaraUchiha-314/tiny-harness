---
type: evidence
workItem: issue-34
---

# Final validation: show the configured remote agents to the model

> Summarised from [`testing-plan.md` § Verification results](../testing-plan.md#verification-results)
> and the review fixes after it, mapped onto the acceptance criteria.

**The headline:** with a real model (`gpt-6.1-sol`), harness A was configured with one
remote agent and asked "What is the status of order 48213?". The model delegated to
that agent by itself, with a self-contained goal, and answered with its result.
Before this change the model had no way to learn the agent existed
([manual-delegation.md](manual-delegation.md)).

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1.1 roster in every context | Scenario "The model's context lists a configured remote agent" reads the real request's `instructions`; T11 startup log `agents roster: ledger` | [integration.md](integration.md), [manual-delegation.md](manual-delegation.md) |
| R1.2 id, name, description, skills | Same scenario asserts each field. `test_each_agent_is_listed_by_id_with_card_fields_and_skills` | [integration.md](integration.md), [unit.md](unit.md) |
| R1.3 no URL or config | `test_the_roster_never_reads_the_agent_url`; scenario asserts neither the URL nor `127.0.0.1` is in `instructions` | [unit.md](unit.md), [integration.md](integration.md) |
| R1.4 `(no agents)` | `test_no_agents_renders_a_plain_marker`, `test_the_agents_section_defaults_to_no_agents` | [unit.md](unit.md) |
| R1.5 static, byte-identical, sorted | `test_the_agents_roster_is_static_never_compacted_and_stable_across_turns`, `test_agents_are_sorted_by_id`; scenario "The durable engine renders the same agents section on every turn" | [unit.md](unit.md), [integration.md](integration.md) |
| R1.6 refused card not listed | Unchanged path: a card failing `validate_card` stops `RemoteAgent.connect`, so it is never registered (existing `tests/security/test_remote_card.py`) | [security.md](security.md) |
| R1.7 never compacted | `agents` in `NEVER_COMPACT`; `test_compaction_keeps_the_never_compact_sections_intact` now includes it | [unit.md](unit.md) |
| R2.1 delegation guidance | `test_default_prompt_says_when_and_how_to_delegate_to_an_agent` checks each point. T11: the real model followed it | [unit.md](unit.md), [manual-delegation.md](manual-delegation.md) |
| R2.2 `agent` parameter description | Regenerated `spawn_subtask.json`, pinned by the contract test | [contract.md](contract.md) |
| R2.3 section extendable | `test_a_plugin_prompt_extends_the_agents_section`; `SECTION_ORDER` pinned | [unit.md](unit.md), [contract.md](contract.md) |
| R3.1 unknown id → `agent.unknown`, no sub-task | Scenario "A spawn_subtask naming an unknown agent is refused without a sub-task"; unit and abuse-case 4 tests; critic C1 fix (`71c1545`) for a registered empty id | [integration.md](integration.md), [security.md](security.md), [critic-review.md](critic-review.md) |
| R3.2 known id delegates as before | Scenario "A spawn_subtask naming a listed agent still delegates to it"; existing delegation scenarios pass (20 in `tests/integration/agents`). T11 full round trip | [integration.md](integration.md), [manual-delegation.md](manual-delegation.md) |
| R3.3 null runs locally | `test_a_null_agent_runs_locally_as_before` | [unit.md](unit.md) |
| R4.1 caps with `…` | `test_long_fields_are_cut_to_their_cap_and_reported`, `test_skills_beyond_the_cap_are_counted_not_listed`, abuse case 3 | [unit.md](unit.md), [security.md](security.md) |
| R4.2 one WARNING per truncated field | Scenario "Startup logs the roster and each truncated card field"; critic C2 fix (`433f694`) with `test_each_truncated_skill_field_is_reported_by_its_position` | [integration.md](integration.md), [critic-review.md](critic-review.md) |
| NFR both engines | Durable-engine scenario above | [integration.md](integration.md) |
| NFR observability | `INFO agents roster: …` asserted in the scenario and seen in T11 | [integration.md](integration.md), [manual-delegation.md](manual-delegation.md) |
| NFR docs | Capability and user docs updated in this PR | [documentation.md](documentation.md) |
| Security abuse cases 1–4 | One negative test each, plus the end-to-end hostile-card scenario; security review passed | [security.md](security.md), [security-review.md](security-review.md) |

**Regression:** pre-commit on all files passed. The full integration suite passed
(111), and the unit, contract and security suites passed again after the review fixes
(693). See [ci-parity.md](ci-parity.md).
