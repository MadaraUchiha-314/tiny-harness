"""T3: the channel extension's JSON schema is committed and pinned (R13.4, R23.2)."""

import json
import os
from pathlib import Path

import tiny_harness.harness.channels
import tiny_harness.harness.persistence
from tests.contract._api import assert_snapshot
from tiny_harness.harness.channels import ChannelMessageData

DOCS = Path(__file__).resolve().parents[2] / "docs" / "a2a" / "ext"


def test_channel_extension_schema_matches_the_committed_file() -> None:
    schema = ChannelMessageData.model_json_schema()
    schema["$id"] = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/channel/v1/schema.json"
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    path = DOCS / "channel.json"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(rendered)
    assert rendered == path.read_text(), "channel extension schema changed; review and regenerate"


def test_channels_and_persistence_api_snapshots() -> None:
    assert_snapshot(tiny_harness.harness.channels)
    assert_snapshot(tiny_harness.harness.persistence)
