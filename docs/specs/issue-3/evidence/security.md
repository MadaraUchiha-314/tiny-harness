# Security and abuse-case tests — T8

One negative test per row of `design.md` § Security design's abuse-case table (cases 2 to
9; case 1, the unauthenticated client, is the perimeter's by decision-003 and has no
harness test). This is also the record the `security-review` node reads.

```text
## uv run pytest tests/security -q
........................                                                 [100%]
24 passed in 2.92s
```

## Tests by abuse case

| Abuse case | Test module |
|---|---|
| 2 — a tool call outside the registry or its schema | `test_tool_boundary.py`, `test_schema_drift.py` |
| 3 — a plugin escaping its directory or expanding variables in `command` | `test_plugin_paths.py` |
| 4 — a non-member on a channel, a non-participant on a task | `test_channel_membership.py`, `test_ingress.py`, `test_role_change.py` |
| 5 — a remote card requiring what the harness does not implement, or a security scheme | `test_remote_card.py` |
| 6 — a credential reaching a log, a span, a record or an exception | `test_redactor.py`, `test_push_token.py` |
| 7 — an oversized or flooding request | `test_oversized_request.py` |
| 9 — a forged A2UI action naming a surface the task did not create | `test_a2ui_action.py` |

Collected tests:

```text
test_a2ui_action.py::test_unknown_a2ui_action_discarded
test_channel_membership.py::test_non_member_rejected_without_task_existence
test_ingress.py::test_ingress_redacted_before_history
test_oversized_request.py::test_oversized_request_not_persisted
test_oversized_request.py::test_flooding_peer_is_rate_limited_before_the_route
test_plugin_paths.py::test_plugin_path_escape_rejected
test_plugin_paths.py::test_command_with_expansion_rejected
test_plugin_paths.py::test_only_the_two_variables_expand_and_only_in_args_env_cwd
test_plugin_paths.py::test_contained_rejects_symlink_and_dotdot_escapes
test_plugin_paths.py::test_skill_and_prompt_paths_outside_the_root_are_skipped
test_push_token.py::test_push_token_encrypted_at_rest
test_push_token.py::test_push_key_must_be_base64_of_a_valid_aes_key
test_redactor.py::test_redactor_masks_tokens
test_redactor.py::test_configured_secret_values_are_masked_whatever_their_shape
test_redactor.py::test_short_or_ordinary_text_is_untouched
test_redactor.py::test_scrub_model_recurses_and_keeps_non_strings
test_redactor.py::test_scrub_returns_the_same_instance_when_nothing_changes
test_redactor.py::test_enum_fields_keep_their_type
test_remote_card.py::test_remote_card_with_unknown_required_ext_refused
test_remote_card.py::test_remote_card_with_security_scheme_refused
test_role_change.py::test_role_change_requires_admin
test_schema_drift.py::test_schema_drift_refuses_invoke
test_tool_boundary.py::test_injected_tool_call_not_executed
test_tool_boundary.py::test_unknown_tool_rejected
```
