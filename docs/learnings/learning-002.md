# Learning 002: Framework routes with root-level path parameters shadow your own

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-3

## What happened

`create_app` appended the `/ui` static mount and `/_monitor` after the a2a-sdk's REST
routes. The SDK's REST binding has root-level path parameters, so `/ui/` and
`/_monitor` matched an SDK route first and answered 404 while the agent card and
JSON-RPC worked. Layer 8 shipped `ui_dir` without a request-level test of `/ui/`.

## Learning

When composing routes from an SDK's route factory, add the application's own routes
*before* the factory's, and pin each with a request-level test rather than trusting
the mount.

## Action

`tests/unit/service/test_app_routes.py` requests `/ui/`, `/ui/index.html`,
`/_monitor` and the card through the real app. The deployment guide's `ui_dir` row is
the documented behaviour.
