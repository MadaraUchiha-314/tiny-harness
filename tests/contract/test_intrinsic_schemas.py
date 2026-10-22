"""T3: the intrinsic tools' schemas match the files committed under docs/a2a/ext/intrinsics/.

Set ``UPDATE_API_SNAPSHOTS=1`` to regenerate the files on purpose.
"""

import json
import os
from pathlib import Path
from typing import cast

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


def test_generate_image_schema_is_the_designs() -> None:
    """issue-38 R2.1: ``{prompt <= 4000, size?, alt <= 200}``, nothing else."""
    schema = definition(IntrinsicName.GENERATE_IMAGE).input_schema
    properties = cast(dict[str, dict[str, object]], schema["properties"])
    assert set(properties) == {"prompt", "size", "alt"}
    assert sorted(cast(list[str], schema["required"])) == ["alt", "prompt"]
    assert properties["prompt"]["maxLength"] == 4000
    assert properties["alt"]["maxLength"] == 200
    assert "1024x1024" in json.dumps(properties["size"])
    assert "1536x1024" in json.dumps(properties["size"])
    assert "1024x1536" in json.dumps(properties["size"])
