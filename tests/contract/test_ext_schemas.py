"""T3 (issue-25): the status and commands extensions' JSON schemas are committed and pinned
(R4.2, R4.3, R6.7), and the card advertises both (R4.2, R6.7)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.protobuf import json_format

from tiny_harness.harness.commands import (
    BUILTIN_SPECS,
    COMMANDS_EXT_URI,
    CommandsExtensionParams,
    commands_extension_schema,
)
from tiny_harness.harness.core import (
    STATUS_EXT_URI,
    StatusExtensionData,
    SubState,
    status_extension_schema,
)
from tiny_harness.service.a2a.card import AgentDescription, build_agent_card

DOCS = Path(__file__).resolve().parents[2] / "docs" / "a2a" / "ext"


def pinned(name: str, schema: dict[str, object]) -> None:
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path = DOCS / name
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(rendered)
    assert rendered == path.read_text(), f"{name} changed; review and regenerate"


def test_status_schema_documents_both_sub_states_without_a_closed_enum() -> None:
    schema = status_extension_schema()
    pinned("status.json", schema)
    assert schema["$id"] == f"{STATUS_EXT_URI}/schema.json"
    assert schema["additionalProperties"] is False
    sub_state = json.dumps(schema["properties"])
    assert '"enum"' not in sub_state and "$ref" not in sub_state
    assert all(s.value in sub_state for s in SubState)
    # the writer's model still validates every documented value
    assert {StatusExtensionData(sub_state=s).sub_state for s in SubState} == set(SubState)


def test_commands_schema_is_the_card_params_model() -> None:
    schema = commands_extension_schema()
    pinned("commands.json", schema)
    assert schema["$id"] == f"{COMMANDS_EXT_URI}/schema.json"
    params = CommandsExtensionParams(commands=BUILTIN_SPECS)
    assert CommandsExtensionParams.model_validate(params.model_dump()) == params


def test_the_card_advertises_status_and_the_registered_commands() -> None:
    card = build_agent_card(AgentDescription(), "http://127.0.0.1:8080", commands=BUILTIN_SPECS)
    extensions = {e.uri: e for e in card.capabilities.extensions}
    assert extensions[STATUS_EXT_URI].required is False
    assert extensions[COMMANDS_EXT_URI].required is False
    params = json_format.MessageToDict(extensions[COMMANDS_EXT_URI].params)
    assert CommandsExtensionParams.model_validate(params).commands == BUILTIN_SPECS
    assert params["commands"][0] == {
        "name": "model",
        "description": "Show or choose this task's model",
        "argument_hint": "[<model>]",
    }
    bare = build_agent_card(AgentDescription(), "http://127.0.0.1:8080")
    empty = next(e for e in bare.capabilities.extensions if e.uri == COMMANDS_EXT_URI)
    assert json_format.MessageToDict(empty.params) == {"commands": []}
