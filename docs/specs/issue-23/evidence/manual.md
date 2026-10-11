---
type: evidence
workItem: issue-23
row: T11
---

# Manual check: a leftover push key and a fresh store (T11)

`tiny-harness serve` in embedded mode, started with `TINY_HARNESS_PUSH_KEY` set to a
value generated for the run (`openssl rand -base64 32`, not recorded) and a
`[store] sqlite_path` that did not exist. Run at `34dccbc` on 2026-10-11 from a script
(server killed by PID).

| Check | Result | Requirement |
|---|---|---|
| server comes up | listening after 6 s | R1.2 |
| warnings naming the variable | exactly 1 | R1.3 |
| occurrences of the key's value in the server log | 0 | R1.3, abuse 3 |
| new store file and its WAL/SHM modes | `600` each | R3.2, abuse 1 |
| `SIGTERM` | exit 0 | — |

```text
listening_after=6s
key_in_log=0
warning_lines=1
600 <run>/state/tiny-harness.sqlite3
600 <run>/state/tiny-harness.sqlite3-shm
600 <run>/state/tiny-harness.sqlite3-wal
serve_exit=0
```

The warning line, as logged:

```json
{"level": "WARNING", "logger": "tiny_harness.runtime", "msg": "TINY_HARNESS_PUSH_KEY is set and ignored; push-notification credentials are protected at rest by the store", "ts": "2026-10-11T19:05:25.849848+00:00"}
```
