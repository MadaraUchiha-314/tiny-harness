# Learning 013: Several agents in one process share every process-wide default

- **Date:** 2026-10-13
- **Source:** system-feedback (issue-36 self-review rounds 1–2 and critic round 1)
- **Work item:** issue-36

## What happened

The harness was written for one agent per process. Running several agents in one
process meant finding each default they silently shared. The design found these:

- the task queue;
- the heartbeat schedule id;
- the participant id;
- the store;
- the embedded Temporal server.

The reviews then found four more:

- the plugin data folder (beside the store);
- the namespace in the shared Temporal pool key;
- the public URL in the local card registry;
- the logging context variable, left set on an in-process caller.

Each one let two agents see or overwrite each other's state, or let one agent's start fail
in a misleading way.

## Learning

When a component that assumed "one per process" becomes "many per process", list every
value it derives from configuration or from module state. Then either key it by the
instance (agent id, public URL, namespace), or claim it in one registry that refuses a
second holder. Give the default instance the old value, so existing deployments do not
move.
