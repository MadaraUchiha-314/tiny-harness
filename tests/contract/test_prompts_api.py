"""T3: the prompt entity API and the default prompt's section names are pinned."""

import tiny_harness.harness.prompts
from tests.contract._api import assert_snapshot
from tiny_harness.harness.prompts import SECTION_ORDER, load_default_system_prompt


def test_prompts_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.prompts)


def test_default_prompt_sections_snapshot() -> None:
    assert tuple(s.name for s in load_default_system_prompt().sections) == SECTION_ORDER
