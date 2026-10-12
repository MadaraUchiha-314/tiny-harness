"""The push URL a stand-in registers on a remote task, and the only form of its token the
harness keeps (issue-27). A leaf module, so the activities and the A2A server share it."""

from __future__ import annotations

import hashlib
from urllib.parse import quote


def push_url(base_url: str, task_id: str) -> str:
    """Where a stand-in asks to be told: this server and the local id, nothing the remote
    agent supplied (abuse case 9)."""
    return f"{base_url.rstrip('/')}/a2a/push/{quote(task_id, safe='')}"


def token_digest(token: str) -> str:
    """The only form of a push token the harness keeps (abuse case 7). The token is 256
    random bits, so a fast hash leaves nothing to guess."""
    return hashlib.sha256(token.encode()).hexdigest()


__all__ = ["push_url", "token_digest"]
