# Decision 010: Media by reference: bytes in one task-scoped store

- **Status:** proposed (accepted when the issue-38 pull request is approved)
- **Date:** 2026-10-22
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #38](https://github.com/MadaraUchiha-314/tiny-harness/issues/38)

## Context

Issue #38 makes a conversation carry images and audio in both directions, with spoken
replies streamed to the user. Every A2A event of a task sits in the workflow's event
log, which is in Temporal history. A Temporal payload is limited to 2 MB, so one 5 MB
photo inline in a message fails outright. The redactor scans every message, so base64
in a message is also megabytes of text to scan and a risk of bytes in logs. Two
surfaces must show the same media of a task, and a spoken reply must start to play
before the whole of it exists.

## Decision

1. **Bytes live in one place.** A task-scoped `MediaStore` (the default
   `FileMediaStore`: `<media root>/<task_id>/<media_id>`) holds every image and audio
   file of a task: what the user sent, what the agent generated and what it spoke.
2. **Everything else carries a reference.** The executor's `MediaIntake` validates each
   `raw` file part, stores it and rewrites it to a `url` file part before the message
   enters the workflow and before redaction. Workflow history, activity payloads and
   `LLMRequest`s carry `MediaRef`s. Only `invoke_llm`, `transcribe`, `speak` and the
   `generate_image` tool activity read bytes, and `MediaAttachment` refuses to serialise
   with its bytes set.
3. **One route serves media to every surface.** `GET /media/{task_id}/{media_id}`
   applies the task's participant check and answers `404` otherwise. Any participant
   reads any medium of the task from any surface.
4. **Speech streams over the route, not over A2A.** A spoken reply is a growing object
   in the store. The A2A event is one `speech:<id>` artifact with its URL, emitted
   before the reply's final status. The audio flows over plain HTTP as the `speak`
   activity appends it, and a retried attempt writes a new, fenced generation.

## Alternatives considered

- **Bytes inline in A2A messages and history.** This is the simplest. It was rejected
  because it breaks Temporal's payload limit for ordinary photos and puts base64 in front
  of the redactor and the logs.
- **A2A artifact `append` chunks for speech.** This is the protocol's own streaming
  shape. It was rejected because each chunk would be an event in workflow history.
- **Temporal's external payload storage (a codec that offloads large payloads).** This
  keeps history small, but media would still pass through the workflow, the redactor
  and every activity, and surfaces would still need a way to fetch it.
- **Let the surfaces send media to the provider directly.** This was rejected because
  surfaces would need provider keys.

## Consequences

- The server and the worker must share the media store. The file store needs one host
  or a shared file system. A multi-host deployment needs an object-storage
  `MediaStore`, which the interface admits but this work item does not ship.
- A plain A2A client sees media as `url` file parts. It must send `X-Participant-Id` (or
  pass the host's participant check) to read them, and must know the media extension to play
  speech while it grows.
- Retention has one more kind (`[retention] media`). The sweep and `tasks purge` delete
  a task's media with its record.
- Logs and traces carry media ids and sizes only.
