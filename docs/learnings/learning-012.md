# Learning 012: FastAPI 0.143 includes routers lazily and ignores a route class's `app`

- **Date:** 2026-10-13
- **Source:** system-feedback (a probe during the issue-36 design)
- **Work item:** issue-36

## What happened

The issue-36 design first planned to give a FastAPI router a custom `APIRoute` subclass
whose `app` wraps the endpoint in the harness's 503 gate and limits, as a2a-sdk's own
`add_a2a_routes_to_fastapi` does. A probe on FastAPI 0.143 showed these facts:

- `include_router` no longer copies routes. It wraps the router in `_IncludedRouter`.
- The overridden `APIRoute.app` is never called.
- A `Mount` inside a router is dropped, so the router cannot serve `/ui`.
- A route appended to `router.routes` directly keeps its bare path. Only
  `add_api_route` applies the router's prefix.
- An `include_router(prefix=…)` sets no `root_path`.
- `include_router` does merge the router's `lifespan`.

## Learning

Before a design relies on a framework's routing internals, run a ten-line probe against
the pinned version. Per-route behaviour in a FastAPI router belongs in router
`dependencies`. A check of where a router is mounted must compare the full request path,
because the include prefix is invisible to the route.
