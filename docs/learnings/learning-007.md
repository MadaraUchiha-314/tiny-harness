# Learning 007: The Temporal dev server initialises only a missing database file

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-17

## What happened

design.md planned to pre-create the embedded Temporal database with `os.open(…, 0o600)`
so it would never be readable by others. The dev server treats an existing file as
already set up. Given an empty one, it failed with `no such table: namespaces`, and the
SDK reported only that the server "did not start within 5s". Unit tests with a stubbed
server passed. Only the integration test against the real binary failed.

## Learning

Don't create files on behalf of a third-party server. Tighten them after the server
creates them, before any sensitive data is written. Prove file-mode claims against the
real process, not a stub.

## Action

`EmbeddedTemporal` tightens the database and its `-wal`/`-shm` files to `0600` before
start, when the file exists, and right after start. The restart scenario asserts the real
server's files end up at `0600`.
