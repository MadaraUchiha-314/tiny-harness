"""``Claims`` (issue-36 R5.3, R5.8): what one process's running harnesses hold.

Two harnesses with the same agent id, the same Temporal namespace and task queue, or the
same store file would run each other's tasks or read each other's records. A harness claims
all three before it connects to anything, so a clash stops it before a worker polls
(abuse case 4). The registry covers one process; the deploy guide asks operators not to give
two processes one agent id.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from tiny_harness.errors import HarnessConflictError


@dataclass(frozen=True)
class Claim:
    agent_id: str
    namespace: str
    task_queue: str
    store_path: Path
    resolved_store: Path = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_store", self.store_path.resolve())


class Claims:
    """A lock-guarded registry of the agent ids, queues and store files in use."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[str, Claim] = {}

    def claim(self, wanted: Claim) -> None:
        """Hold all three of ``wanted``'s keys, or raise naming the first clash and its
        holder and hold nothing."""
        with self._lock:
            for holder in self._held.values():
                clash = _clash(holder, wanted)
                if clash:
                    raise HarnessConflictError(
                        f"another harness in this process already uses {clash}",
                        holder=holder.agent_id,
                    )
            self._held[wanted.agent_id] = wanted

    def release(self, held: Claim) -> None:
        with self._lock:
            if self._held.get(held.agent_id) is held:
                del self._held[held.agent_id]

    def held(self) -> int:
        with self._lock:
            return len(self._held)


def _clash(holder: Claim, wanted: Claim) -> str:
    if holder.agent_id == wanted.agent_id:
        return f"agent id {wanted.agent_id!r}"
    if (holder.namespace, holder.task_queue) == (wanted.namespace, wanted.task_queue):
        return f"task queue {wanted.task_queue!r} in namespace {wanted.namespace!r}"
    if holder.resolved_store == wanted.resolved_store:
        return f"store file {wanted.resolved_store}"
    return ""


PROCESS_CLAIMS = Claims()
"""The process's one registry; every ``Harness`` claims through it."""


__all__ = ["PROCESS_CLAIMS", "Claim", "Claims"]
