"""T3: the intrinsic tools' schemas match the files committed under docs/a2a/ext/intrinsics/.

Set ``UPDATE_API_SNAPSHOTS=1`` to regenerate the files on purpose.
"""

import json
import os
from pathlib import Path

import pytest

from tiny_harness.harness.tools.intrinsics import IntrinsicName, definition, definitions

DOCS = Path(__file__).resolve().parents[2] / "docs" / "a2a" / "ext" / "intrinsics"


@pytest.mark.parametrize("name", list(IntrinsicName))
def test_intrinsic_schema_matches_the_committed_file(name: IntrinsicName) -> None:
    rendered = json.dumps(definition(name).model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    path = DOCS / f"{name.value}.json"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
    assert rendered == path.read_text(), f"{name.value}: schema changed; review and regenerate"


def test_every_intrinsic_is_an_intrinsic_with_a_strict_schema() -> None:
    for d in definitions():
        assert d.execution.value == "intrinsic"
        assert d.input_schema.get("additionalProperties") is False
        assert d.description
