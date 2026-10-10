"""T3: the tiny-harness task extension's JSON schema is committed and pinned (R8.3, R23.2)."""

import json
import os
from pathlib import Path

import tiny_harness.harness.core
from tests.contract._api import assert_snapshot
from tiny_harness.harness.core import TaskExtensionData

DOCS = Path(__file__).resolve().parents[2] / "docs" / "a2a" / "ext"


def test_task_extension_schema_matches_the_committed_file() -> None:
    schema = TaskExtensionData.model_json_schema()
    schema["$id"] = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/task/v1/schema.json"
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path = DOCS / "task.json"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(rendered)
    assert rendered == path.read_text(), "task extension schema changed; review and regenerate"
    assert schema["additionalProperties"] is False


def test_core_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.core)
