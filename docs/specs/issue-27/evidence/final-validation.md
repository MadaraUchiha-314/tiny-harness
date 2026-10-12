---
type: evidence
workItem: issue-27
---

# Final validation: Remote sub-tasks hear remote state changes between turns

> Summarised from `testing-plan.md` § Verification results and the review rounds. The
> raw output is in the files beside this one.

## Final validation evidence

The ticket's acceptance sketch comes first, then the EARS criteria.

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| **Ticket:** a remote sub-task that a third party completes or cancels while parked shows the new state on the parent's stream, with no message sent to it | A third party cancels the remote task. The push reaches `/a2a/push/<id>`, the stand-in ends CANCELED, the parent's row shows CANCELED and its model is told, and the remote's model saw exactly one request. | `test_a_third_party_cancel_is_heard_through_push`, [integration.md](integration.md) |
| **Ticket:** the same against an agent without push support, through follow | A third-party completion is heard by following (`updates = "follow"`), and a cancel against a card without push (`auto`) | `test_without_push_the_stand_in_follows_and_hears_a_completion`, `test_a_card_without_push_is_followed` |
| **Ticket:** a push with a wrong or missing token is refused and nothing changes | Missing, wrong, unknown-id, `TaskWorkflow`-id, other-remote-task and ended-stand-in pushes: all `401`, with no update or activity recorded and the state unchanged | `tests/security/test_remote_push.py`, [security.md](security.md) |
| R1.1–1.3 register a push config with a 256-bit token at `<base_url>/a2a/push/<local id>` | The URL is asserted from the remote's store, and `push_url` and the digest are unit-tested | `test_a_third_party_cancel_…`, `test_push_receiver.py` |
| R1.4 reconcile after registration | The fetch is counted in history | `test_pushes_during_a_turn_are_applied_after_it`, the forged-push test |
| R1.5 a failed registration falls back to follow, without the token in logs or traces | Scenario test, plus a unit test with an error carrying the token: no exported span, no log line | `test_a_failed_registration_falls_back_to_follow`, `test_a_failed_registration_exports_no_span_and_logs_no_token` |
| R1.6 `X-Participant-Id` on every remote call | Replies, get, subscribe and push-config calls succeed against a tiny-harness peer, including a reply from a differently named local participant (red without the fix) | `test_a_reply_while_following_cancels_the_follow` |
| R2.1–2.4 receive, verify, wake, fetch, relay only on change | Receiver unit tests (ordering and statuses). The forged push sends no `child_done`. | `test_push_receiver.py`, `test_a_forged_terminal_push_is_not_applied` |
| R2.5 awaiting-next-message → COMPLETED | Unit test | `test_remote_out.py` |
| R2.6, R2.6a end on terminal; roll over while parked | The cancel tests; a stand-in rolls over past `history_event_bound` and still hears a cancel | `test_a_long_parked_stand_in_continues_as_new` |
| R2.7 parent noted only on terminal or interrupted states | A remote resumed by a third party: COMPLETED is noted and WORKING never is | `test_a_remote_resumed_by_a_third_party_wakes_the_model_only_at_its_end` |
| R2.8 pushes during a turn are applied after it | One fetch after the turn, no rechecks, no WORKING note | `test_pushes_during_a_turn_are_applied_after_it` |
| R2.9 re-fetch while the fetch disagrees with the claim | Exactly four fetches for a forged claim; a failed last recheck keeps the stand-in alive | the forged-push test, `test_a_fetch_failing_on_the_last_recheck_…` |
| R3.1–3.4 follow, re-subscribe pacing, window bound, cancelled by a reply | Unit tests of the activity (window, interval, non-remote agent); the reply cancels the follow (`ACTIVITY_TASK_CANCEL_REQUESTED` asserted); a redacted text does not spin | `test_follow_activity.py`, `test_a_reply_while_following_…`, `test_a_redacted_status_text_…` |
| R4.1–4.5 `updates` and `follow_interval` | Config unit tests; `off` keeps today's behaviour | `test_config_agents.py`, `test_updates_off_keeps_todays_behaviour` |
| R5.1–5.3 delete on every exit, a failed delete tolerated, later pushes refused | Config gone after a cancel or terminal state; a failed delete still ends CANCELED; a push after the end is `401` | `test_the_push_config_is_deleted_…`, `test_a_failed_cleanup_…`, `test_a_push_to_an_ended_stand_in_is_refused` |
| Abuse cases 1–9 | One negative test each | [security-review.md](security-review.md), `testing-plan.md` T8 |
| Regression | Full suite, 772 passed | [regression.md](regression.md), [unit.md](unit.md), [contract.md](contract.md), [static.md](static.md) |
