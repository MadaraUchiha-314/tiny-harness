"""The plugin loader (R3.1-R3.9): discover, validate, contain, expand, register.

Loading follows the specification's rules: a manifest that fails its schema is fatal
for the whole plugin (``PluginError``, nothing loaded); a component that fails loads is
skipped with its reason while the rest continue; component types the harness does not
support (legacy SSE servers) are skipped. The two security rules of the design are here
too: every component path and ``cwd`` must resolve inside the plugin root (or the plugin
data directory for ``${PLUGIN_DATA}``), and only ``${PLUGIN_ROOT}`` and ``${PLUGIN_DATA}``
expand, in ``args``, ``env`` values and ``cwd``, never in ``command`` (abuse case 3).
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast

import jsonschema
from mcp import StdioServerParameters
from pydantic import ValidationError

from tiny_harness.errors import ComponentSkipped, PluginError, TinyHarnessError
from tiny_harness.harness.hooks import (
    HookContext,
    HookExecutor,
    HookManager,
    HookPoint,
    JsonRpcHookExecutor,
    McpHookExecutor,
    Operation,
    Phase,
    Providers,
)
from tiny_harness.harness.plugins.models import (
    MCP_SCHEMA_ID,
    NAMESPACE,
    PLUGIN_DATA_VAR,
    PLUGIN_ROOT_VAR,
    PLUGIN_SCHEMA_ID,
    ComponentKind,
    HookDef,
    HooksFile,
    LoadedComponent,
    LoadReport,
    McpConfig,
    McpHttpServer,
    McpSseServer,
    McpStdioServer,
    Plugin,
    PluginManifest,
    SkippedComponent,
)

SCHEMAS = Path(__file__).parent / "schemas"
_PLUGIN_SCHEMA = cast(dict[str, object], json.loads((SCHEMAS / "plugin.schema.json").read_text()))
_MCP_SCHEMA = cast(dict[str, object], json.loads((SCHEMAS / "mcp.schema.json").read_text()))
JsonObject = dict[str, object]


class Registrar(Protocol):
    """Where the loader hands each discovered component. Later layers implement the
    skill loader, the MCP tool source and the prompt entity behind this protocol; raising
    any ``TinyHarnessError`` skips that one component with its reason."""

    async def register_skill(self, plugin: Plugin, path: Path) -> str: ...

    async def register_mcp_server(
        self, plugin: Plugin, name: str, server: McpStdioServer | McpHttpServer
    ) -> str: ...

    async def register_prompt(self, plugin: Plugin, path: Path) -> str: ...

    async def register_system_prompt(self, plugin: Plugin, path: Path) -> str: ...


# --- containment and expansion (R3.6, R3.7) ---------------------------------------------


def contained(path: Path, root: Path) -> Path:
    """``path`` resolved, required to be inside ``root``; else ``ComponentSkipped``."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ComponentSkipped("path escapes the plugin root", path=str(path), root=str(root))
    return resolved


def expand(value: str, *, root: Path, data: Path) -> str:
    """Expand ``${PLUGIN_ROOT}`` and ``${PLUGIN_DATA}`` and nothing else."""
    return value.replace(f"${{{PLUGIN_ROOT_VAR}}}", str(root)).replace(
        f"${{{PLUGIN_DATA_VAR}}}", str(data)
    )


def resolve_cwd(cwd: str, *, root: Path, data: Path) -> Path:
    """A ``cwd`` is ``./``-relative, ``${PLUGIN_ROOT}``-rooted or ``${PLUGIN_DATA}``-rooted,
    and stays inside the directory it is rooted in after expansion (spec § 7.2.1)."""
    if cwd.startswith(f"${{{PLUGIN_DATA_VAR}}}"):
        return contained(Path(expand(cwd, root=root, data=data)), data)
    if cwd.startswith(f"${{{PLUGIN_ROOT_VAR}}}"):
        return contained(Path(expand(cwd, root=root, data=data)), root)
    if cwd.startswith("./"):
        return contained(root / cwd, root)
    raise ComponentSkipped(
        "cwd must be ./-relative, ${PLUGIN_ROOT} or ${PLUGIN_DATA} rooted", cwd=cwd
    )


def prepare_stdio(server: McpStdioServer, *, root: Path, data: Path) -> StdioServerParameters:
    """The MCP SDK parameters for a stdio server, with the security rules applied."""
    if "${" in server.command:
        raise PluginError(
            "variable expansion is not allowed in command",
            manifest_path=str(root / "mcp.json"),
            command=server.command,
        )
    command = server.command
    if command.startswith("./"):
        command = str(contained(root / command, root))
    args = [expand(a, root=root, data=data) for a in server.args]
    env = {k: expand(v, root=root, data=data) for k, v in server.env.items()}
    env[PLUGIN_ROOT_VAR] = str(root)
    env[PLUGIN_DATA_VAR] = str(data)
    cwd = resolve_cwd(server.cwd, root=root, data=data) if server.cwd else None
    return StdioServerParameters(command=command, args=args, env=env, cwd=cwd)


# --- discovery -----------------------------------------------------------------------------


def _read_json(path: Path) -> JsonObject:
    try:
        raw = cast(object, json.loads(path.read_text()))
    except (OSError, ValueError) as exc:
        raise PluginError(f"cannot read {path.name}: {exc}", manifest_path=str(path)) from exc
    if not isinstance(raw, dict):
        raise PluginError(f"{path.name} is not a JSON object", manifest_path=str(path))
    return cast(JsonObject, raw)


def parse_manifest(path: Path) -> tuple[PluginManifest, tuple[str, ...]]:
    """Validate ``plugin.json`` against the published schema after stripping what the
    specification makes non-fatal: unknown top-level fields and a non-object ``extensions``."""
    raw = _read_json(path)
    notes: list[str] = []
    allowed = set(cast(Mapping[str, object], _PLUGIN_SCHEMA["properties"]).keys())
    for key in [k for k in raw if k not in allowed]:
        notes.append(f"ignored unknown top-level field {key!r}")
        del raw[key]
    if "extensions" in raw and not isinstance(raw["extensions"], dict):
        notes.append("ignored non-object extensions field")
        del raw["extensions"]
    try:
        jsonschema.validate(raw, _PLUGIN_SCHEMA)
        manifest = PluginManifest.model_validate(raw)
    except (jsonschema.ValidationError, ValidationError) as exc:
        raise PluginError(
            f"plugin.json fails the 1.0.0 schema: {exc}", manifest_path=str(path)
        ) from exc
    if manifest.schema_id != PLUGIN_SCHEMA_ID:
        raise PluginError("unsupported Agent Plugins version", manifest_path=str(path))
    return manifest, tuple(notes)


def parse_mcp(path: Path) -> McpConfig:
    raw = _read_json(path)
    try:
        jsonschema.validate(raw, _MCP_SCHEMA)
        config = McpConfig.model_validate(raw)
    except (jsonschema.ValidationError, ValidationError) as exc:
        raise ComponentSkipped(f"mcp.json fails the 1.0.0 schema: {exc}", path=str(path)) from exc
    if config.schema_id != MCP_SCHEMA_ID:
        raise ComponentSkipped("mcp.json targets another Agent Plugins version", path=str(path))
    return config


def discover(root: Path) -> Plugin:
    """Read a plugin directory into a ``Plugin``; only the manifest is fatal (R3.5)."""
    root = root.resolve()
    manifest, notes_list = parse_manifest(root / "plugin.json")
    notes = list(notes_list)
    skills: list[Path] = []
    skills_dir = root / "skills"
    if skills_dir.exists():
        if skills_dir.is_dir():
            for child in sorted(skills_dir.iterdir()):
                if child.is_dir() and (child / "SKILL.md").is_file():
                    skills.append(child)
        else:
            notes.append("skills is not a directory; skills disabled")
    mcp: dict[str, McpStdioServer | McpHttpServer | McpSseServer] = {}
    mcp_path = root / "mcp.json"
    if mcp_path.exists():
        try:
            mcp = dict(parse_mcp(mcp_path).mcp_servers)
        except ComponentSkipped as exc:
            notes.append(f"MCP disabled for this plugin: {exc.message}")
    hooks: tuple[HookDef, ...] = ()
    prompts: list[Path] = []
    systemprompt: Path | None = None
    ns = root / NAMESPACE
    if ns.is_dir():
        hooks_file = ns / "hooks.json"
        if hooks_file.is_file():
            try:
                hooks = HooksFile.model_validate(_read_json(hooks_file)).hooks
            except (PluginError, ValidationError) as exc:
                notes.append(f"hooks.json ignored: {exc}")
        prompts_dir = ns / "prompts"
        if prompts_dir.is_dir():
            prompts = sorted(p for p in prompts_dir.glob("*.md") if p.is_file())
        if (ns / "systemprompt.md").is_file():
            systemprompt = ns / "systemprompt.md"
    return Plugin(
        manifest=manifest,
        root=root,
        skills=tuple(skills),
        mcp=mcp,
        hooks=hooks,
        prompts=tuple(prompts),
        systemprompt=systemprompt,
        notes=tuple(notes),
    )


# --- the loader -----------------------------------------------------------------------------


def _parse_points(names: tuple[str, ...] | None) -> tuple[HookPoint, ...] | None:
    if names is None:
        return None
    points: list[HookPoint] = []
    for name in names:
        operation, _, phase = name.rpartition(".")
        try:
            points.append(HookPoint(operation=Operation(operation), phase=Phase(phase)))
        except ValueError as exc:
            raise ComponentSkipped("unknown hook point", point=name) from exc
    return tuple(points)


def _import_executor(import_path: str) -> HookExecutor:
    module_name, sep, attr = import_path.partition(":")
    if not sep or not attr:
        raise ComponentSkipped("import_path must be module:attribute", import_path=import_path)
    try:
        target = cast(object, getattr(importlib.import_module(module_name), attr))
    except (ImportError, AttributeError) as exc:
        raise ComponentSkipped(f"cannot import hook: {exc}", import_path=import_path) from exc
    if isinstance(target, HookExecutor):
        return target
    if callable(target):
        produced = cast(Callable[[], object], target)()
        if isinstance(produced, HookExecutor):
            return produced
    raise ComponentSkipped("import_path is not a HookExecutor", import_path=import_path)


class PluginLoader:
    """Loads plugins into the hook manager and the registrar (R3.4), first the built-in
    plugin, then the operator's, in order; ``override`` is the loading configuration's
    declaration that a later plugin may replace an earlier registration (R3.8)."""

    def __init__(
        self,
        *,
        hook_manager: HookManager,
        registrar: Registrar,
        providers: Providers | None = None,
        data_root: Path,
    ) -> None:
        self._hooks = hook_manager
        self._registrar = registrar
        self._providers = providers or Providers()
        self._data_root = data_root.resolve()

    async def load_directory(self, root: Path, *, override: bool = False) -> LoadReport:
        return await self.load(discover(root), override=override)

    async def load(self, plugin: Plugin, *, override: bool = False) -> LoadReport:
        loaded: list[LoadedComponent] = []
        skipped: list[SkippedComponent] = []
        root = plugin.root
        data = self._data_root / plugin.manifest.name

        def skip(kind: ComponentKind, id_: str, exc: TinyHarnessError) -> None:
            skipped.append(SkippedComponent(kind=kind, id=id_, code=exc.code, reason=str(exc)))

        for path in plugin.skills:
            try:
                skill_path = contained(path, root) if root else path
                loaded.append(
                    LoadedComponent(
                        kind=ComponentKind.SKILL,
                        id=await self._registrar.register_skill(plugin, skill_path),
                    )
                )
            except TinyHarnessError as exc:
                skip(ComponentKind.SKILL, path.name, exc)
        for name, server in plugin.mcp.items():
            try:
                if isinstance(server, McpSseServer):
                    raise ComponentSkipped("legacy HTTP+SSE servers are not supported", server=name)
                if isinstance(server, McpStdioServer) and root is not None:
                    prepare_stdio(server, root=root, data=data)  # validates; the source re-prepares
                loaded.append(
                    LoadedComponent(
                        kind=ComponentKind.MCP_SERVER,
                        id=await self._registrar.register_mcp_server(plugin, name, server),
                    )
                )
            except TinyHarnessError as exc:
                skip(ComponentKind.MCP_SERVER, name, exc)
        for hook in plugin.hooks:
            try:
                self._hooks.register(self._build_hook(hook, root=root, data=data))
                loaded.append(LoadedComponent(kind=ComponentKind.HOOK, id=hook.name))
            except TinyHarnessError as exc:
                skip(ComponentKind.HOOK, hook.name, exc)
        for path in plugin.prompts:
            try:
                prompt_path = contained(path, root) if root else path
                loaded.append(
                    LoadedComponent(
                        kind=ComponentKind.PROMPT,
                        id=await self._registrar.register_prompt(plugin, prompt_path),
                    )
                )
            except TinyHarnessError as exc:
                skip(ComponentKind.PROMPT, path.stem, exc)
        if plugin.systemprompt is not None:
            try:
                sp = contained(plugin.systemprompt, root) if root else plugin.systemprompt
                loaded.append(
                    LoadedComponent(
                        kind=ComponentKind.SYSTEM_PROMPT,
                        id=await self._registrar.register_system_prompt(plugin, sp),
                    )
                )
            except TinyHarnessError as exc:
                skip(ComponentKind.SYSTEM_PROMPT, "systemprompt", exc)
        return LoadReport(
            plugin=plugin.manifest.name,
            loaded=tuple(loaded),
            skipped=tuple(skipped),
            notes=plugin.notes,
        )

    def _build_hook(self, hook: HookDef, *, root: Path | None, data: Path) -> HookExecutor:
        points = _parse_points(hook.points)
        if hook.import_path is not None:
            executor = _import_executor(hook.import_path)
            if executor.priority != hook.priority or (
                points is not None and executor.points != frozenset(points)
            ):
                return _Reprioritised(executor, hook.priority, points)
            return executor
        if hook.url is not None:
            return JsonRpcHookExecutor(
                hook.name,
                str(hook.url),
                priority=hook.priority,
                points=points,
                http_client_factory=self._providers.http_client_factory,
            )
        assert hook.mcp is not None
        if isinstance(hook.mcp, McpStdioServer):
            if root is None:
                raise ComponentSkipped("a stdio MCP hook needs a plugin root", hook=hook.name)
            server: StdioServerParameters | str = prepare_stdio(hook.mcp, root=root, data=data)
        else:
            server = str(hook.mcp.url)
        return McpHookExecutor(hook.name, server, priority=hook.priority, points=points)


class _Reprioritised:
    """An imported executor with the priority and points the plugin's hooks.json declares."""

    def __init__(
        self, inner: HookExecutor, priority: int, points: tuple[HookPoint, ...] | None
    ) -> None:
        self._inner = inner
        self._priority = priority
        self._points = None if points is None else frozenset(points)

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def points(self) -> frozenset[HookPoint] | None:
        return self._points if self._points is not None else self._inner.points

    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None:
        return await self._inner.handle(point, ctx)


__all__ = [
    "PluginLoader",
    "Registrar",
    "contained",
    "discover",
    "expand",
    "parse_manifest",
    "parse_mcp",
    "prepare_stdio",
    "resolve_cwd",
]
