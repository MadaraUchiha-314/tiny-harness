"""T6: the agent card is pinned; every extension the harness declares is in it (R14.2)."""

from __future__ import annotations

import json
import os

from google.protobuf import json_format

from tests.contract._api import SNAPSHOTS
from tiny_harness.interaction.a2ui import A2UI_EXT_URI, BASIC_CATALOG_ID
from tiny_harness.service.a2a.card import AgentDescription, build_agent_card


def test_agent_card_snapshot() -> None:
    card = build_agent_card(AgentDescription(), "http://127.0.0.1:8080")
    rendered = json.dumps(json_format.MessageToDict(card), indent=2, sort_keys=True) + "\n"
    path = SNAPSHOTS / "agent-card.json"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(rendered)
    assert rendered == path.read_text(), (
        "agent card changed; review and rerun with UPDATE_API_SNAPSHOTS=1"
    )
    a2ui = next(e for e in card.capabilities.extensions if e.uri == A2UI_EXT_URI)
    params = json_format.MessageToDict(a2ui.params)
    assert params == {"supportedCatalogIds": [BASIC_CATALOG_ID], "acceptsInlineCatalogs": False}
