"""The typed error hierarchy shared by every layer (design.md § Error handling).

Every error carries a machine-readable ``code`` (``<area>.<what>``), a message and a
``detail`` map of strings. No error takes a credential-shaped field: a secret never
becomes part of an exception, so it never reaches a log, a span or a task failure
message (abuse case 6). ``to_record()`` is the structured form the o11y plugin logs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar


class TinyHarnessError(Exception):
    """Base of every harness error. Subclasses set ``code``."""

    code: ClassVar[str] = "harness.error"

    def __init__(self, message: str, **detail: str) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict[str, str] = dict(detail)

    def __str__(self) -> str:
        suffix = "".join(f" {k}={v}" for k, v in self.detail.items())
        return f"[{self.code}] {self.message}{suffix}"

    def to_record(self) -> dict[str, str | dict[str, str]]:
        """The structured form for logs and spans: code, message, detail."""
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}


# --- entities and registry (R1) -------------------------------------------------------


class EntityNotFoundError(TinyHarnessError):
    """No registry entry matches the reference; never substituted by a default (R1.3)."""

    code = "entity.not_found"


class VersionNotFoundError(TinyHarnessError):
    """The entity exists but no registered version satisfies the specifier (R1.2)."""

    code = "entity.version_not_found"


class RegistryConflictError(TinyHarnessError):
    """A second registration of the same ``(id, version)`` without an override (R3.8)."""

    code = "entity.conflict"


# --- hooks (R2) -------------------------------------------------------------------------


class AbortReason(StrEnum):
    """Why a hook executor cancelled the operation."""

    REFUSED = "refused"
    POLICY = "policy"
    INVALID = "invalid"


class HookAbort(TinyHarnessError):
    """Raised by an executor to cancel the operation; surfaces as a failure or a refusal (R2.4)."""

    code = "hook.abort"

    def __init__(self, message: str, *, reason: AbortReason, **detail: str) -> None:
        super().__init__(message, reason=reason.value, **detail)
        self.reason = reason


class HookTransportError(TinyHarnessError):
    """A remote hook executor could not be reached; never passed through silently (R2.6)."""

    code = "hook.transport"


# --- plugins and skills (R3, R5) --------------------------------------------------------


class PluginError(TinyHarnessError):
    """A plugin manifest failed validation; none of its components are loaded (R3.5)."""

    code = "plugin.invalid"

    def __init__(self, message: str, *, manifest_path: str, **detail: str) -> None:
        super().__init__(message, manifest_path=manifest_path, **detail)
        self.manifest_path = manifest_path


class ComponentSkipped(TinyHarnessError):
    """One component of a valid plugin failed to load and was skipped (R3.5)."""

    code = "plugin.component_skipped"


class SkillError(TinyHarnessError):
    """A skill directory or its front matter fails the Agent Skills rules (R5.4)."""

    code = "skill.invalid"


# --- tools (R6, R19) ----------------------------------------------------------------------


class ToolNotFoundError(TinyHarnessError):
    """The LLM named a tool that is not in the registry; nothing is executed (R6.3)."""

    code = "tool.not_found"


class ToolArgumentError(TinyHarnessError):
    """The call's arguments fail the tool's input schema; the tool is not invoked (R6.4)."""

    code = "tool.invalid_arguments"

    def __init__(self, message: str, *, validation: str, **detail: str) -> None:
        super().__init__(message, validation=validation, **detail)
        self.validation = validation


class ToolNotRetriedError(TinyHarnessError):
    """A non-idempotent tool failed and was not retried automatically (R19.5)."""

    code = "tool.not_retried"


class ToolSchemaChangedError(TinyHarnessError):
    """The MCP server's schema for the tool changed since registration (abuse case 8)."""

    code = "tool.schema_changed"


# --- core (R9, R11, R13) ------------------------------------------------------------------


class PlanCycleError(TinyHarnessError):
    """The plan's steps would form a cycle (R9.5)."""

    code = "plan.cycle"


class StoreWriteError(TinyHarnessError):
    """A persistence write failed; the operation is not reported complete (R11.3)."""

    code = "store.write_failed"


class ChannelMembershipError(TinyHarnessError):
    """The sender is not a member of the channel, or the caller not a participant (R13.3)."""

    code = "channel.not_a_member"


# --- A2A (R7, R14) ------------------------------------------------------------------------


class UnsupportedExtensionError(TinyHarnessError):
    """An extension the card does not advertise, or a remote card's unknown requirement."""

    code = "a2a.unsupported_extension"


# --- configuration and providers (R21, R18) -----------------------------------------------


class ConfigError(TinyHarnessError):
    """Configuration is missing or invalid; the process refuses to start (R21.2)."""

    code = "config.invalid"

    def __init__(self, message: str, *, variable: str, **detail: str) -> None:
        super().__init__(message, variable=variable, **detail)
        self.variable = variable


class ProviderError(TinyHarnessError):
    """A provider SDK failed in a way durable execution must not retry (a 4xx)."""

    code = "provider.failed"

    def __init__(self, message: str, *, provider: str, status: int, **detail: str) -> None:
        super().__init__(message, provider=provider, status=str(status), **detail)
        self.provider = provider
        self.status = status


class RetryableProviderError(TinyHarnessError):
    """A provider SDK failed in a way durable execution may retry (R18.3)."""

    code = "provider.retryable"
    retryable: ClassVar[bool] = True

    def __init__(self, message: str, *, provider: str, status: int, **detail: str) -> None:
        super().__init__(message, provider=provider, status=str(status), **detail)
        self.provider = provider
        self.status = status


__all__ = [
    "AbortReason",
    "ChannelMembershipError",
    "ComponentSkipped",
    "ConfigError",
    "EntityNotFoundError",
    "HookAbort",
    "HookTransportError",
    "PlanCycleError",
    "PluginError",
    "ProviderError",
    "RegistryConflictError",
    "RetryableProviderError",
    "SkillError",
    "StoreWriteError",
    "TinyHarnessError",
    "ToolArgumentError",
    "ToolNotFoundError",
    "ToolNotRetriedError",
    "ToolSchemaChangedError",
    "UnsupportedExtensionError",
    "VersionNotFoundError",
]
