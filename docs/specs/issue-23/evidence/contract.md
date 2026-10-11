---
type: evidence
workItem: issue-23
row: T3
---

# Contract snapshots (T3)

The public-API and settings-schema snapshots pass at `34dccbc`: 30 passed. The only
snapshot changes since `e5b3d64` (0.5.0) are the ones this work item intends.

```text
$ uv run pytest tests/contract -q
30 passed in 2.77s
```

## Snapshot diff since 0.5.0

```diff
diff --git c/tests/contract/snapshots/settings.schema.json w/tests/contract/snapshots/settings.schema.json
index 46c93ba..20fa7e8 100644
--- c/tests/contract/snapshots/settings.schema.json
+++ w/tests/contract/snapshots/settings.schema.json
@@ -662,13 +662,6 @@
       "title": "Plugins",
       "type": "array"
     },
-    "push_key": {
-      "description": "from TINY_HARNESS_PUSH_KEY; encrypts push-config tokens",
-      "format": "password",
-      "title": "Push Key",
-      "type": "string",
-      "writeOnly": true
-    },
     "retention": {
       "$ref": "#/$defs/RetentionConfig",
       "default": {
@@ -710,8 +703,7 @@
   "required": [
     "temporal",
     "openai",
-    "server",
-    "push_key"
+    "server"
   ],
   "title": "Settings",
   "type": "object"
diff --git c/tests/contract/snapshots/tiny_harness.config.txt w/tests/contract/snapshots/tiny_harness.config.txt
index eafe86a..394d172 100644
--- c/tests/contract/snapshots/tiny_harness.config.txt
+++ w/tests/contract/snapshots/tiny_harness.config.txt
@@ -11,7 +11,7 @@ model RetentionConfig(tasks: <class 'datetime.timedelta'> = ..., plans: <class '
 model RetryPolicies(default: <class 'tiny_harness.config.RetryPolicySpec'> = ..., per_activity: collections.abc.Mapping[str, tiny_harness.config.RetryPolicySpec] = ...)
 model RetryPolicySpec(initial_interval: <class 'datetime.timedelta'> = ..., backoff_coefficient: <class 'float'> = ..., maximum_interval: <class 'datetime.timedelta'> = ..., maximum_attempts: <class 'int'> = ..., non_retryable_error_types: tuple[str, ...] = ...)
 model ServerConfig(bind: <class 'str'> = ..., base_url: <class 'pydantic.networks.HttpUrl'>, max_request_bytes: <class 'int'> = ..., rate_limit_per_minute: <class 'int'> = ..., bridge_interval: <class 'datetime.timedelta'> = ..., cors_origins: tuple[str, ...] = ..., ui_dir: pathlib.Path | None = ...)
-model Settings(temporal: <class 'tiny_harness.config.TemporalConfig'>, openai: <class 'tiny_harness.config.OpenAIConfig'>, anthropic: tiny_harness.config.AnthropicConfig | None = ..., server: <class 'tiny_harness.config.ServerConfig'>, heartbeat: <class 'tiny_harness.config.HeartbeatConfig'> = ..., plugins: tuple[pathlib.Path, ...] = ..., agents: tuple[tiny_harness.config.RemoteAgentSpec, ...] = 
+model Settings(temporal: <class 'tiny_harness.config.TemporalConfig'>, openai: <class 'tiny_harness.config.OpenAIConfig'>, anthropic: tiny_harness.config.AnthropicConfig | None = ..., server: <class 'tiny_harness.config.ServerConfig'>, heartbeat: <class 'tiny_harness.config.HeartbeatConfig'> = ..., plugins: tuple[pathlib.Path, ...] = ..., agents: tuple[tiny_harness.config.RemoteAgentSpec, ...] = 
 model StoreConfig(sqlite_path: <class 'pathlib.Path'> = ...)
 model TemporalConfig(mode: typing.Literal['remote', 'embedded'] = ..., address: str | None = ..., namespace: str | None = ..., api_key: pydantic.types.SecretStr | None = ..., task_queue: <class 'str'> = ..., tls: <class 'bool'> = ..., search_attributes: <class 'bool'> = ..., embedded: tiny_harness.config.EmbeddedTemporalConfig | None = ...)
 def load_settings(path: 'Path | None' = None, *, env: 'Mapping[str, str] | None' = None, settings_type: 'type[S]') -> 'S'
diff --git c/tests/contract/snapshots/tiny_harness.harness.persistence.txt w/tests/contract/snapshots/tiny_harness.harness.persistence.txt
index c9cfc0b..f5ad0f8 100644
--- c/tests/contract/snapshots/tiny_harness.harness.persistence.txt
+++ w/tests/contract/snapshots/tiny_harness.harness.persistence.txt
@@ -5,11 +5,7 @@ model CompactionStoreRecord(id: <class 'str'>, context_id: <class 'str'>, task_i
 model Filter(context_id: str | None = ..., task_id: str | None = ..., since: datetime.datetime | None = ..., limit: <class 'int'> = ...)
 model InboxAuditRecord(id: <class 'str'>, context_id: <class 'str'>, task_id: <class 'str'>, created_at: <class 'datetime.datetime'>, kind: typing.Literal['inbox_audit'] = ..., message_id: <class 'str'>, participant_id: str | None, accepted: <class 'bool'>, reason: <class 'str'> = ...)
 model PlanRecord(id: <class 'str'>, context_id: <class 'str'>, task_id: <class 'str'>, created_at: <class 'datetime.datetime'>, kind: typing.Literal['plans'] = ..., plan: <class 'tiny_harness.harness.core.task.Plan'>, turn: <class 'int'>)
-model PushConfigRecord(id: <class 'str'>, context_id: <class 'str'>, task_id: <class 'str'>, created_at: <class 'datetime.datetime'>, kind: typing.Literal['push_configs'] = ..., config_id: <class 'str'>, url: <class 'str'>, token_ciphertext: <class 'str'> = ..., authentication_ciphertext: <class 'str'> = ...)
-class PushTokenCipher(object)
-  def __init__(self, key: 'SecretStr') -> 'None'
-  def decrypt(self, ciphertext: 'str') -> 'str'
-  def encrypt(self, plaintext: 'str') -> 'str'
+model PushConfigRecord(id: <class 'str'>, context_id: <class 'str'>, task_id: <class 'str'>, created_at: <class 'datetime.datetime'>, kind: typing.Literal['push_configs'] = ..., config_id: <class 'str'>, url: <class 'str'>, token: <class 'pydantic.types.SecretStr'> = ..., authentication: <class 'pydantic.types.SecretStr'> = ..., token_ciphertext: <class 'str'> = ..., authentication_ciphertext: <c
 Record = TypeAliasType
 model RecordBase(id: <class 'str'>, context_id: <class 'str'>, task_id: <class 'str'>, created_at: <class 'datetime.datetime'>)
 enum RecordKind: TASKS='tasks', PLANS='plans', STATE='state', CHANNEL_MESSAGES='channel_messages', INBOX_AUDIT='inbox_audit', COMPACTIONS='compactions', PUSH_CONFIGS='push_configs'
```

- `settings.schema.json`: `push_key` gone from `properties` and `required` (R1.4).
- `tiny_harness.config.txt`: `Settings` without `push_key`.
- `tiny_harness.harness.persistence.txt`: `PushTokenCipher` gone; `PushConfigRecord`
  has `token`/`authentication: SecretStr` and the two excluded legacy fields.
