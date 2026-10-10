# Learning 001: A fixture-only client never meets the real transport

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-3

## What happened

The web renderer's SSE parser split frames on `\n\n`. Every test fed it the prototype
fixture or in-memory events, and the Playwright suites ran the `?fixture=prototype`
mode, so the parser was never pointed at the a2a-sdk server, which ends frames with
`\r\n\r\n`. The renderer rendered nothing from a live stream; the first live capture of
the demo found it.

## Learning

A client of a protocol needs at least one test against the real server or a recorded
byte stream of it, not only against hand-written events. Fixtures prove the model and
the rendering; they cannot prove the wire.

## Action

The verification plan's UI row now captures the live demo in both renderers. The
hand-written parser was then replaced by the official `@a2a-js/sdk` client at the
approver's request, which removes the class of defect rather than one instance. When a layer adds a client of
an external SDK's server, its tasks.md entry should name one test that exercises the
real transport.
