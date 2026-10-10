"""T3: the configuration models' public API and JSON schema are pinned."""

import json

import tiny_harness.config
from tests.contract._api import SNAPSHOTS, assert_snapshot
from tiny_harness.config import Settings


def test_config_api_snapshot() -> None:
    assert_snapshot(tiny_harness.config)


def test_settings_json_schema_snapshot() -> None:
    rendered = json.dumps(Settings.model_json_schema(), indent=2, sort_keys=True) + "\n"
    path = SNAPSHOTS / "settings.schema.json"
    if not path.exists():
        path.write_text(rendered)
    assert rendered == path.read_text(), "Settings schema changed; review and update the snapshot"
