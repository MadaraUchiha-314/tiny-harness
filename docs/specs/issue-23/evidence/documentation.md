---
type: evidence
workItem: issue-23
---

# Documentation: Remove `TINY_HARNESS_PUSH_KEY` from the end-to-end architecture

Two capability docs and six user-facing documents changed in PR #24; the architecture
index never mentioned the key and is unchanged.

## Capability docs

| Capability doc | What changed | History row |
|----------------|--------------|-------------|
| [persistence](../../../capabilities/persistence.md) | The "one encrypted exception" rule is now: push-config credentials kept as supplied in `SecretStr` fields, protected at rest by the store; 0.5.x encrypted rows dropped with a warning; a new SQLite file is `0600` | issue-23 |
| [configuration](../../../capabilities/configuration.md) | `TINY_HARNESS_PUSH_KEY` removed from the secrets; a set variable is reported as ignored, like `OPENAI_BASE_URL` | issue-23 |

## Documentation

| Document | What changed |
|----------|--------------|
| `README.md` | the three `export TINY_HARNESS_PUSH_KEY=…` lines removed; the Ollama demo now really needs no key |
| `docs/guide/getting-started.md` | the export line removed |
| `docs/guide/deployment.md` | the secrets-table row removed; a note that the variable is ignored; new "Push-notification credentials" section (stored as supplied, `0600`, encrypting store or volume, retention) with the "Upgrading from 0.5" note (R3.3, R4.3) |
| `examples/demo/README.md` | the export line removed |
| `examples/demo/config.toml`, `config.embedded.toml`, `config.ollama.toml` | the export line removed from each header comment |
| `tiny_harness/service/cli.py` (module docstring, rendered by `--help` readers) | the variable removed from the list of secrets |

Historic specs under `docs/specs/issue-3/`, `issue-17/`, `issue-19/` and `issue-20/`
still mention the key; they record past work and are not edited.

## Checks (testing plan, docs/deps row)

```text
$ grep -rn TINY_HARNESS_PUSH_KEY README.md docs/guide docs/capabilities examples tests tiny_harness
docs/guide/deployment.md:109:`TINY_HARNESS_PUSH_KEY` is no longer read (issue-23). A process that still has it set logs a
docs/guide/deployment.md:128:AES-GCM encrypted under `TINY_HARNESS_PUSH_KEY`. Without the key they cannot be read, so
docs/capabilities/configuration.md:35:- `TINY_HARNESS_PUSH_KEY` SHALL NOT be read; WHEN it is set THEN the runtime SHALL log
docs/capabilities/configuration.md:72:| issue-23 | `TINY_HARNESS_PUSH_KEY` and `Settings.push_key` removed; a set variable is reported as ignored | [spec](../specs/issue-23/), [PR #24](https://github.com/MadaraUchiha-314/tiny-harness/pull/24) |
tests/e2e/demo.py:186:        env.pop("TINY_HARNESS_PUSH_KEY", None)
tests/integration/embedded/test_cli_embedded.py:253:    # issue-23: no TINY_HARNESS_PUSH_KEY either; nothing reads it
tests/integration/embedded/test_cli_embedded.py:254:    unused = ("TEMPORAL_API_KEY", "TINY_HARNESS_PUSH_KEY")
tests/integration/embedded/test_cli_embedded.py:327:    # issue-23: no TINY_HARNESS_PUSH_KEY either; nothing reads it
tests/integration/embedded/test_cli_embedded.py:328:    unused = ("TEMPORAL_API_KEY", "TINY_HARNESS_PUSH_KEY")
tests/unit/service/test_cli.py:78:    monkeypatch.delenv("TINY_HARNESS_PUSH_KEY", raising=False)  # issue-23: never needed
tests/unit/service/test_runtime_model.py:91:    (line,) = ignored_environment_warnings({"TINY_HARNESS_PUSH_KEY": "cHVzaC1rZXktdmFsdWU="})
tests/unit/service/test_runtime_model.py:92:    assert line.startswith("TINY_HARNESS_PUSH_KEY is set and ignored")
tests/unit/service/test_runtime_model.py:99:    env = {"OPENAI_BASE_URL": "http://x/v1", "TINY_HARNESS_PUSH_KEY": "k"}
tests/unit/service/test_runtime_model.py:103:@pytest.mark.parametrize("env", [{}, {"OPENAI_BASE_URL": ""}, {"TINY_HARNESS_PUSH_KEY": ""}])
tiny_harness/service/runtime.py:72:        "TINY_HARNESS_PUSH_KEY",
tiny_harness/service/a2a/push.py:58:        removed ``TINY_HARNESS_PUSH_KEY`` — never deliver it (issue-23 R4)."""
tests/unit/test_config.py:39:    with_key = Settings.load(write(tmp_path), env={**ENV, "TINY_HARNESS_PUSH_KEY": "x"})
```

Every remaining hit is deliberate: the deployment guide's "ignored" and upgrade notes,
the configuration rule that it is not read, the runtime's ignored-variables table and
the legacy-row comment, and tests that unset it or assert it is ignored.

```text
$ grep -rn cryptography pyproject.toml tiny_harness
(no output; exit 1)
```

`cryptography` stays installed as a transitive dependency (`google-auth` via
`a2a-sdk`, `pyjwt[crypto]` via `mcp`), which is not this project's to manage.
