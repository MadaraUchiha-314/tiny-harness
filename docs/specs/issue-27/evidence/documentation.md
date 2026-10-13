# Documentation: issue-27

## Capability docs

| Doc | What changed |
|-----|--------------|
| [remote-agents](../../../capabilities/remote-agents.md) | The push, follow and off watches on a parked remote task; cleanup; when the parent's model is told; `X-Participant-Id` on every remote task call. History row added. |
| [a2a-server](../../../capabilities/a2a-server.md) | `POST /a2a/push/{task_id}` and its refusals; the SDK's request-body DEBUG log dropped. History row added. |
| [configuration](../../../capabilities/configuration.md) | `agents[].updates` and `agents[].follow_interval`. History row added. |

## Documentation

| Doc | What changed |
|-----|--------------|
| [docs/guide/deployment.md](../../../sdk/deploy.md) | The `agents` row names `updates` and `follow_interval`. The `[server]` row says `base_url` is where remote agents push, so it must be reachable from them. |
| `README.md` | Unchanged. It names "a client for remote agents" without describing the watch, and nothing it says became wrong. |
