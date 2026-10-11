---
type: evidence
workItem: issue-23
---

# Final validation: Remove `TINY_HARNESS_PUSH_KEY` from the end-to-end architecture

Every acceptance criterion is met, summarised from the testing plan's
[Verification results](../testing-plan.md#verification-results) (run at `34dccbc`; the
later commits change only docs and a docstring).

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1.1 the variable is not read; `Settings` has no field | unit test; contract snapshot | [unit.md](unit.md), [contract.md](contract.md) |
| R1.2 every process starts without it | unit (`Settings.load`), embedded CLI subprocesses, the Ollama e2e demo — all with the variable unset | [unit.md](unit.md), [integration.md](integration.md), [e2e-ollama.md](e2e-ollama.md) |
| R1.3 a set variable → one warning, value not echoed | unit test; manual `serve` (1 warning, `key_in_log=0`) | [unit.md](unit.md), [manual.md](manual.md) |
| R1.4 settings schema without `push_key` | snapshot diff | [contract.md](contract.md) |
| R2.1–R2.3 set/get/list/delete round-trip; delivery carries the token | integration scenarios 5 and 6 | [integration.md](integration.md) |
| R2.4 push configs stay in the store under `[retention]` | unchanged record kind; scenario 5 reads them from the store | [integration.md](integration.md) |
| R3.1 no harness-side encryption | unit/security test: stored row holds the credential as supplied | [security.md](security.md) |
| R3.2 new SQLite file `0600` | security test; manual `stat` of db, `-wal`, `-shm` | [security.md](security.md), [manual.md](manual.md) |
| R3.3 deployment guide states the at-rest model | "Push-notification credentials" section | [documentation.md](documentation.md) |
| R4.1, R4.2 legacy rows dropped, warned, never delivered | integration scenario 7 (T10) | [integration.md](integration.md) |
| R4.3 upgrade note | deployment guide "Upgrading from 0.5"; `BREAKING CHANGE` footer of `70b439b` | [documentation.md](documentation.md) |
| R5.1, R5.2 docs no longer ask for the key; persistence rule rewritten | grep check; capability docs | [documentation.md](documentation.md) |
| R5.3 demo and fixtures run without it | e2e demo pops it; fixtures dropped it | [e2e-ollama.md](e2e-ollama.md) |
| R5.4 `cryptography` dropped | grep check; integration suite exercises the worker sandbox | [documentation.md](documentation.md), [integration.md](integration.md) |
| Abuse cases 1–4 | negative tests | [security.md](security.md) |
