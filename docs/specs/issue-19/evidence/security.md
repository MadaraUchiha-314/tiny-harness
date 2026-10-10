---
type: evidence
workItem: issue-19
row: T8
---

# Security and abuse cases (T8)

Every abuse case in design § Security design has a negative test, and each passes; the
whole-harness scenarios also pass inside a network namespace with only loopback, so the
harness needs no network to run against a local endpoint (R6.2). Run at `420df50`.

## Abuse-case tests

```text
$ env -u OPENAI_API_KEY -u TEMPORAL_API_KEY uv run pytest -v tests/unit tests/integration/compat -k "abuse or security"
tests/unit/models/test_openai_chat.py::test_abuse_an_unparseable_body_is_a_provider_error[no_choices.json] PASSED
tests/unit/models/test_openai_chat.py::test_abuse_an_unparseable_body_is_a_provider_error[bad_arguments.json] PASSED
tests/unit/models/test_openai_chat.py::test_abuse_unparseable_streamed_arguments_are_a_provider_error PASSED
tests/unit/models/test_openai_endpoint.py::test_abuse_openai_base_url_in_the_environment_is_ignored[http://127.0.0.1:11434/v1] PASSED
tests/unit/models/test_openai_endpoint.py::test_abuse_openai_base_url_in_the_environment_is_ignored[None] PASSED
tests/unit/models/test_openai_endpoint.py::test_abuse_a_redirect_from_a_custom_endpoint_is_refused PASSED
tests/unit/models/test_openai_malformed.py::test_abuse_an_unparseable_body_is_a_provider_error[arguments] PASSED
tests/unit/models/test_openai_malformed.py::test_abuse_an_unparseable_body_is_a_provider_error[usage] PASSED
tests/unit/models/test_openai_malformed.py::test_abuse_a_body_that_is_not_json_is_a_provider_error PASSED
tests/unit/models/test_openai_malformed.py::test_abuse_unparseable_streamed_tool_arguments_are_a_provider_error PASSED
tests/unit/service/test_a2a_units.py::test_the_card_advertises_every_extension_and_no_security_scheme PASSED
tests/unit/service/test_runtime_model.py::test_abuse_the_origin_drops_path_and_query[https://h.example:8443/v1?api-key=leak#frag-https://h.example:8443] PASSED
tests/unit/service/test_runtime_model.py::test_abuse_the_origin_drops_path_and_query[http://[::1]:11434/v1-http://[::1]:11434] PASSED
tests/unit/service/test_runtime_model.py::test_abuse_the_origin_drops_path_and_query[None-https://api.openai.com] PASSED
tests/unit/service/test_runtime_model.py::test_abuse_a_translated_error_does_not_carry_the_key PASSED
tests/unit/test_config_openai.py::test_abuse_a_key_over_http_to_a_non_loopback_host_is_refused[http://10.0.0.5/v1] PASSED
tests/unit/test_config_openai.py::test_abuse_a_key_over_http_to_a_non_loopback_host_is_refused[http://ollama.lan:11434/v1] PASSED
tests/unit/test_config_openai.py::test_abuse_a_key_over_http_to_a_non_loopback_host_is_refused[http://localhost.evil.invalid/v1] PASSED
tests/unit/test_config_openai.py::test_abuse_the_http_rule_also_holds_for_a_config_built_in_code PASSED
tests/unit/test_config_openai.py::test_abuse_credentials_in_the_base_url_are_refused[http://u:p@127.0.0.1:11434/v1] PASSED
tests/unit/test_config_openai.py::test_abuse_credentials_in_the_base_url_are_refused[https://u@openrouter.ai/api/v1] PASSED
tests/unit/test_layout.py::test_modules_mirror_diagram[tiny_harness.harness.security] PASSED
====================== 22 passed, 323 deselected in 0.48s ======================
```

Two of the 22 (`test_a2a_units…no_security_scheme`, `test_layout…security`) are existing
tests the `-k` filter also matches.

| Abuse case | Test(s) |
|------------|---------|
| 1 `OPENAI_BASE_URL` redirects | `test_abuse_openai_base_url_in_the_environment_is_ignored` (both with and without a `base_url`) |
| 2 key over clear-text `http` | `test_abuse_a_key_over_http_to_a_non_loopback_host_is_refused`, `test_abuse_the_http_rule_also_holds_for_a_config_built_in_code`; accepted cases in `test_a_key_over_http_to_loopback_is_accepted`, `test_http_to_a_network_host_without_a_key_is_accepted` |
| 3 credentials in the URL | `test_abuse_credentials_in_the_base_url_are_refused` |
| 4 malformed body | the five `test_abuse_…unparseable…` / `…not_json…` tests across both APIs, invoke and stream |
| 5 key in logs or errors | `test_abuse_the_origin_drops_path_and_query`, `test_abuse_a_translated_error_does_not_carry_the_key`, `test_secret_values_include_the_key_only_when_it_is_set` |
| design § headers | `test_organization_and_project_are_not_sent_to_a_custom_endpoint` (T1) |
| design § redirects | `test_abuse_a_redirect_from_a_custom_endpoint_is_refused` |

## Offline: the scenarios with no network

```text
$ unshare -rn sh -c 'ip link set lo up && ip -brief addr && \
    env -u OPENAI_API_KEY -u TEMPORAL_API_KEY .venv/bin/pytest -v tests/integration/compat'
lo               UNKNOWN        127.0.0.1/8 ::1/128
tests/integration/compat/test_compat_endpoint.py::test_harness_completes_a_task_against_a_responses_endpoint PASSED
tests/integration/compat/test_compat_endpoint.py::test_harness_completes_a_task_against_a_chat_completions_endpoint PASSED
tests/integration/compat/test_compat_endpoint.py::test_a_retryable_endpoint_failure_is_retried_and_the_task_completes PASSED
======================== 3 passed, 20 warnings in 3.74s ========================
```

The namespace has only the loopback interface: the embedded Temporal (from the cached
CLI), the A2A server and the model endpoint all ran on `127.0.0.1`, and nothing else was
reachable.
