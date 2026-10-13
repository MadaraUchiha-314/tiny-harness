# Learning 010: The A2A SDK logs request bodies and span errors where no redactor reaches

- **Date:** 2026-10-12
- **Source:** system-feedback
- **Work item:** issue-27

## What happened

A test asserting that a push token never appears in captured logs failed. The A2A SDK's
JSON-RPC dispatcher logs every request body at DEBUG (`Request body: …`), which includes
a registered push config's token. The critic round then found the client-side twin: the
SDK's traced transports call `record_exception` and `set_status(ERROR, str(e))`, so an
error that echoes a request would export it in a span. The harness's redactor covers only
its own logger and its own spans.

## Learning

Before sending a credential through a third-party SDK, check its logging and tracing for
request bodies and exception text. A credential the redactor does not know by value
needs its path closed at the source: a logger filter, or spans kept from export.

## Action

`DropRequestBodies` filters the dispatcher's DEBUG record. `no_export()` together with the
`ExportGuard` span processor keeps spans started during push registration from export.
