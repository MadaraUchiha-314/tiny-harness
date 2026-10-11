---
type: evidence
workItem: issue-19
row: T6
---

# Contract snapshots (T6)

The public API changed only additively, plus `OpenAIConfig.api_key` becoming optional
(a relaxation: every configuration that loaded before still loads). Run at `420df50`;
the `OpenAIConfig` line below is as of `ac8a0a5`, after critic round 1 made
`context_window_tokens` a strict integer (`gt=0` lives in the field's schema, not the
rendered type).

```text
$ uv run pytest -q tests/contract
30 passed in 2.82s

$ git diff --stat 755ccb6 -- tests/contract/snapshots
 tests/contract/snapshots/settings.schema.json      | 60 +++++++++++++++++++---
 tests/contract/snapshots/tiny_harness.config.txt   |  2 +-
 .../snapshots/tiny_harness.harness.core.txt        |  4 +-
 .../snapshots/tiny_harness.harness.models.txt      |  4 +-
 4 files changed, 57 insertions(+), 13 deletions(-)
```

## `tiny_harness.config.txt`

```diff
-model OpenAIConfig(api_key: <class 'pydantic.types.SecretStr'>, model: <class 'str'> = ..., timeout: <class 'datetime.timedelta'> = ..., max_output_tokens: <class 'int'> = ...)
+model OpenAIConfig(api_key: pydantic.types.SecretStr | None = ..., base_url: pydantic.networks.HttpUrl | None = ..., api: typing.Literal['responses', 'chat_completions'] = ..., model: <class 'str'> = ..., timeout: <class 'datetime.timedelta'> = ..., max_output_tokens: <class 'int'> = ..., context_window_tokens: typing.Annotated[int, Strict(strict=True)] | None = ...)
```

## `tiny_harness.harness.core.txt`

```diff
-model LLMInvokedPost(task_id: <class 'str'>, correlation_id: <class 'str'>, attempt: <class 'int'> = ..., request: <class 'tiny_harness.harness.models.llm.LLMRequest'>, response: <class 'tiny_harness.harness.models.llm.LLMResponse'>)
-model LLMInvokedPre(task_id: <class 'str'>, correlation_id: <class 'str'>, attempt: <class 'int'> = ..., request: <class 'tiny_harness.harness.models.llm.LLMRequest'>)
+model LLMInvokedPost(task_id: <class 'str'>, correlation_id: <class 'str'>, attempt: <class 'int'> = ..., request: <class 'tiny_harness.harness.models.llm.LLMRequest'>, model: tiny_harness.harness.models.llm.LLMModelInfo | None = ..., response: <class 'tiny_harness.harness.models.llm.LLMResponse'>)
+model LLMInvokedPre(task_id: <class 'str'>, correlation_id: <class 'str'>, attempt: <class 'int'> = ..., request: <class 'tiny_harness.harness.models.llm.LLMRequest'>, model: tiny_harness.harness.models.llm.LLMModelInfo | None = ...)
```

## `tiny_harness.harness.models.txt`

```diff
-model LLMModelInfo(provider: <class 'str'>, model: <class 'str'>, context_window_tokens: <class 'int'>, min_cacheable_tokens: <class 'int'> = ...)
+model LLMModelInfo(provider: <class 'str'>, model: <class 'str'>, context_window_tokens: <class 'int'>, min_cacheable_tokens: <class 'int'> = ..., endpoint: str | None = ..., api: str | None = ...)
-  def __init__(self, api_key: 'SecretStr', *, model: 'str' = 'gpt-6.1-sol', timeout: 'timedelta' = datetime.timedelta(seconds=60), max_output_tokens: 'int' = 2000, client: 'AsyncOpenAI | None' = None) -> 'None'
+  def __init__(self, api_key: 'SecretStr | None', *, model: 'str' = 'gpt-6.1-sol', timeout: 'timedelta' = datetime.timedelta(seconds=60), max_output_tokens: 'int' = 2000, base_url: 'str | None' = None, api: 'WireApi' = 'responses', context_window_tokens: 'int | None' = None, client: 'AsyncOpenAI | None' = None) -> 'None'
```

## `settings.schema.json`

The only removed lines restructure `OpenAIConfig.api_key` (from a required string to an
optional `string | null`) and drop it from `required`; the rest adds the `base_url`,
`api` and `context_window_tokens` properties and the new docstring.
