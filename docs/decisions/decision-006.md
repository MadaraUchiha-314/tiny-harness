# Decision 006: The model endpoint is configuration-only, and a custom endpoint reuses `OPENAI_API_KEY`

- **Status:** proposed (accepted when the issue-19 pull request is approved)
- **Date:** 2026-10-10
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #19](https://github.com/MadaraUchiha-314/tiny-harness/issues/19)

## Context

Issue #19 asks that tiny-harness call any OpenAI-compatible URL — Ollama, OpenRouter and
the like — "in the config section related to OpenAI". The OpenAI SDK already has two
ambient ways to do that: it reads `OPENAI_BASE_URL` when no URL is passed, and it copies
`OPENAI_ORG_ID` / `OPENAI_PROJECT_ID` into every request. Before this work item the first
of those was live: exporting `OPENAI_BASE_URL` silently redirected every prompt, tool
result and the API key to another host, with nothing in the configuration file to say so.

## Decision

1. **`[openai] base_url` is the only way to choose the endpoint.** The adapter always
   builds its client with an explicit URL (`https://api.openai.com/v1` when none is
   configured), so `OPENAI_BASE_URL` is ignored. A custom endpoint also gets no
   organization or project headers and no redirects.
2. **A custom endpoint reuses `OPENAI_API_KEY`,** which becomes optional when `base_url`
   is set. There is no second key variable.
3. **One adapter, two wire APIs.** `[openai] api` selects the Responses API (default) or
   Chat Completions inside `OpenAILLM`; there is no separate adapter class.
4. **The endpoint fails closed.** `base_url` must be `http` or `https`, must carry no
   `user:password@`, and must use `https` to send a key to anything but a literal
   loopback host.

## Consequences

- The endpoint a deployment talks to is always visible in its configuration file and in
  the startup log line (`model endpoint <origin> api=<api> model=<model>`).
- An operator who exports a real OpenAI key and points `base_url` at a third party sends
  that key to the third party. The configuration reference says so; a separate variable
  would have prevented it at the cost of a second name for the same secret.
- A server behind a redirecting proxy must be configured with its final URL.

## Alternatives considered

- **Honour `OPENAI_BASE_URL`.** Rejected: an environment variable could redirect the
  harness's traffic and key without any change to the reviewed configuration.
- **A separate key variable for custom endpoints** (e.g. `TINY_HARNESS_MODEL_API_KEY`).
  Offered at the requirements gate; the requirements were approved with
  `OPENAI_API_KEY`, as the ticket asked.
- **A second adapter class for Chat Completions.** Rejected: configuration, client,
  errors, model info and key handling are shared; only mapping and parsing differ.
