"""A registrar that records what the loader hands it (tests of the loader itself)."""

from __future__ import annotations

from pathlib import Path

from tiny_harness.errors import RegistryConflictError
from tiny_harness.harness.plugins import McpHttpServer, McpStdioServer, Plugin


class RecordingRegistrar:
    def __init__(self) -> None:
        self.skills: dict[str, Path] = {}
        self.mcp: dict[str, McpStdioServer | McpHttpServer] = {}
        self.prompts: dict[str, Path] = {}
        self.system_prompt: Path | None = None
        self.override = False

    def _claim(self, kind: str, store: dict[str, object], id_: str) -> None:
        if id_ in store and not self.override:
            raise RegistryConflictError("already registered", kind=kind, id=id_)

    async def register_skill(self, plugin: Plugin, path: Path) -> str:
        self._claim("skill", dict(self.skills), path.name)
        self.skills[path.name] = path
        return path.name

    async def register_mcp_server(
        self, plugin: Plugin, name: str, server: McpStdioServer | McpHttpServer
    ) -> str:
        self._claim("mcp_server", dict(self.mcp), name)
        self.mcp[name] = server
        return name

    async def register_prompt(self, plugin: Plugin, path: Path) -> str:
        self._claim("prompt", dict(self.prompts), path.stem)
        self.prompts[path.stem] = path
        return path.stem

    async def register_system_prompt(self, plugin: Plugin, path: Path) -> str:
        if self.system_prompt is not None and not self.override:
            raise RegistryConflictError(
                "already registered", kind="system_prompt", id="systemprompt"
            )
        self.system_prompt = path
        return "systemprompt"
