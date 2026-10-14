"""``uv run python -m examples.multi_agent.app``: five agents in one Starlette app (issue-36).

Each agent has its own configuration (``a.toml`` … ``e.toml``), its own path under
``/agents/<id>``, its own task queue and store, and one shared embedded Temporal dev server.
Agent ``a`` delegates to ``b`` and ``c``, and ``b`` to ``d``, through their ``[[agents]]``
tables: over HTTP, through each other's routes, as between two services.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount

from tiny_harness.config import Settings
from tiny_harness.service import Harness, harnesses_lifespan

HERE = Path(__file__).parent
AGENTS = ("a", "b", "c", "d", "e")


def load(name: str) -> Settings:
    return Settings.load(HERE / f"{name}.toml")


def build_app(
    settings: Sequence[Settings], *, harness: Callable[[Settings], Harness] = Harness
) -> tuple[Starlette, list[Harness]]:
    """One Starlette app mounting one harness per settings at the path of its base URL."""
    harnesses = [harness(s) for s in settings]
    app = Starlette(
        routes=[Mount(h.prefix, app=h.asgi_app()) for h in harnesses],
        lifespan=harnesses_lifespan(*harnesses),
    )
    return app, harnesses


def main() -> None:
    import uvicorn

    from tiny_harness.service.process import observe

    settings = [load(name) for name in AGENTS]
    os.makedirs(HERE / ".state", exist_ok=True)
    observe(settings[0])
    app, harnesses = build_app(settings)
    for h in harnesses:
        print(f"agent {h.agent_id}: {h.public_url}")
    uvicorn.run(app, host="127.0.0.1", port=8090)


if __name__ == "__main__":
    main()
