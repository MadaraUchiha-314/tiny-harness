"""``uv run python -m examples.multi_agent.app_fastapi``: the same five agents as ``app.py``,
each included in one FastAPI app as a router, with their routes in ``/docs`` (issue-36 R3).
Needs ``pip install 'tiny_harness[fastapi]'``."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

from fastapi import FastAPI

from examples.multi_agent.app import AGENTS, HERE, load
from tiny_harness.config import Settings
from tiny_harness.fastapi import harness_router
from tiny_harness.service import Harness


def build_app(
    settings: Sequence[Settings], *, harness: Callable[[Settings], Harness] = Harness
) -> tuple[FastAPI, list[Harness]]:
    """One FastAPI app with one router per agent; each router carries its harness's
    lifespan and its prefix, so ``include_router`` takes no further prefix."""
    harnesses = [harness(s) for s in settings]
    app = FastAPI(title="Five agents")
    for h in harnesses:
        app.include_router(harness_router(h))
    return app, harnesses


def main() -> None:
    import uvicorn

    from tiny_harness.service.process import observe

    settings = [load(name) for name in AGENTS]
    os.makedirs(HERE / ".state", exist_ok=True)
    observe(settings[0])
    app, _ = build_app(settings)
    uvicorn.run(app, host="127.0.0.1", port=8090)


if __name__ == "__main__":
    main()
