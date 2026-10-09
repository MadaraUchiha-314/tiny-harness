"""Agent state (R10.1): typed, schema-described, with plugin-registered subsets.

``AgentState`` is what the workflow carries between turns: the conversation history
(each entry an ``InputItem`` with an id, so compaction can name what it removed), the
running summary, the loaded skills, the last usage, and ``data``, a JSON object whose
named subsets a plugin may describe with a JSON schema; a write to a described subset
is validated before it is accepted.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

import jsonschema
from pydantic import BaseModel, ConfigDict, Field

from tiny_harness.errors import TinyHarnessError
from tiny_harness.harness.models import InputItem, Usage
from tiny_harness.jsontypes import JsonObject, JsonSchema, JsonValue


class StateValidationError(TinyHarnessError):
    """A write to a schema-described subset of the agent state failed validation."""

    code = "state.invalid"


class HistoryEntry(BaseModel, frozen=True):
    """One item of the conversation history, numbered so compaction can cite it."""

    id: int
    item: InputItem


class LoadedSkillRecord(BaseModel, frozen=True):
    """A skill the LLM loaded: its body goes in the never-compact set, its tools are live."""

    name: str
    body: str
    tools: tuple[str, ...] = ()


class SchemaValidated(BaseModel, frozen=True):
    """A JSON object with optional per-subset schemas (R10.1)."""

    data: JsonObject = Field(default_factory=dict)
    schemas: Mapping[str, JsonSchema] = Field(default_factory=dict)

    def register(self, subset: str, schema: JsonSchema) -> Self:
        return self.model_copy(update={"schemas": {**self.schemas, subset: schema}})

    def write(self, subset: str, value: JsonValue) -> Self:
        schema = self.schemas.get(subset)
        if schema is not None:
            try:
                jsonschema.validate(value, schema)
            except jsonschema.ValidationError as exc:
                raise StateValidationError(
                    "state write fails the subset's schema", subset=subset, error=exc.message
                ) from exc
        return self.model_copy(update={"data": {**self.data, subset: value}})

    def read(self, subset: str) -> JsonValue:
        return self.data.get(subset)


class AgentState(BaseModel, frozen=True):
    """Everything the loop needs between turns; immutable, updated by copy."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    history: tuple[HistoryEntry, ...] = ()
    next_history_id: int = 1
    summary: str = ""
    loaded_skills: tuple[LoadedSkillRecord, ...] = ()
    data: SchemaValidated = SchemaValidated()
    last_usage: Usage | None = None
    last_context_chars: int = 0
    turn: int = 0

    def append(self, *items: InputItem) -> AgentState:
        entries = list(self.history)
        next_id = self.next_history_id
        for item in items:
            entries.append(HistoryEntry(id=next_id, item=item))
            next_id += 1
        return self.model_copy(update={"history": tuple(entries), "next_history_id": next_id})

    def with_skill(self, record: LoadedSkillRecord) -> AgentState:
        others = tuple(s for s in self.loaded_skills if s.name != record.name)
        return self.model_copy(update={"loaded_skills": (*others, record)})

    def without_skill(self, name: str) -> AgentState:
        return self.model_copy(
            update={"loaded_skills": tuple(s for s in self.loaded_skills if s.name != name)}
        )

    def after_turn(self, usage: Usage, context_chars: int) -> AgentState:
        return self.model_copy(
            update={"last_usage": usage, "last_context_chars": context_chars, "turn": self.turn + 1}
        )


__all__ = [
    "AgentState",
    "HistoryEntry",
    "LoadedSkillRecord",
    "SchemaValidated",
    "StateValidationError",
]
