"""T3: the plugin loader's public API is pinned."""

import json
import os
from pathlib import Path

import tiny_harness.harness.plugins
from tests.contract._api import assert_snapshot
from tiny_harness.harness.plugins import CommandsFile

DOCS = Path(__file__).resolve().parents[2] / "docs" / "plugins"
SCHEMA_ID = "https://madarauchiha-314.github.io/tiny-harness/plugins/commands/v1/schema.json"


def test_plugins_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.plugins)


def test_commands_json_schema_matches_the_committed_file() -> None:
    """issue-25 R6a.6: the plugin ``commands.json`` schema is generated from the model."""
    schema = CommandsFile.model_json_schema()
    schema["$id"] = SCHEMA_ID
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path = DOCS / "commands.json"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
    assert rendered == path.read_text(), "commands.json schema changed; review and regenerate"
    assert schema["additionalProperties"] is False
