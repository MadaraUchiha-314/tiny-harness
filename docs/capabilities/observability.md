# Capability: observability

> One structured log line and one span per lifecycle operation, following the
> OpenTelemetry GenAI conventions, redacted, exported to OTLP, Langfuse or a file; built
> as a plugin on the hooks.

## What it is

How an incident is reconstructed without a debugger. The o11y plugin registers one hook
executor on every `pre` and `post` point; Temporal's and MCP's own integrations
propagate the trace context, so one trace spans the request, the workflow, every retry
and the tools. Lives in `tiny_harness/service/o11y/`.

## Current behaviour

- Every operation SHALL produce a JSON log record with the task id, the correlation id,
  the operation, the phase and the attempt, at the same level and format in every
  environment (`[o11y] log_level`).
- `pre` SHALL open a span and make it current, so provider and MCP spans nest under it;
  `post` SHALL close it with the GenAI attributes: `invoke_agent tiny-harness`,
  `chat <model>` with `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` and
  `gen_ai.usage.cache_read.input_tokens`, `execute_tool <name>` with `gen_ai.tool.name`.
  `activity.failed` records the failure on the open span. `tool_calls.extracted` is
  pre-only.
- Spans SHALL be keyed by task, correlation id, operation and attempt, so a retried
  attempt is a new span under the same activity.
- Trace context SHALL propagate through Temporal with `TracingInterceptor` on the client
  (and therefore on every worker of that client: the worker adds none of its own) and
  through MCP calls with the SDK's `traceparent`.
- Export SHALL go to `otlp_endpoint` when set, to Langfuse through its OTLP ingestion
  endpoint when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set, and to
  `trace_file` as one JSON object per finished span when set; tests inject an exporter.
- Every log field and span attribute SHALL pass through the redactor; no secret is
  logged and credential-shaped values in tool arguments and results are masked.

## Design

[design.md § Observability](../specs/issue-3/design.md#observability-r17--serviceo11y).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | The o11y executor, logging, tracing and plugin (Layer 6); the JSON-lines exporter and the single-interceptor fix (Layer 9) | [spec](../specs/issue-3/), [PR #12](https://github.com/MadaraUchiha-314/tiny-harness/pull/12) |
