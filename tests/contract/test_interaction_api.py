"""T3 (issue-38): the renderer-neutral interaction API is public: ``Modality`` gains
``IMAGE`` and ``AUDIO``, ``RenderItem`` the ``media`` kind with ``url`` and ``name``."""

import tiny_harness.interaction.renderer
import tiny_harness.interaction.surface
from tests.contract._api import assert_snapshot


def test_renderer_api_snapshot() -> None:
    assert_snapshot(tiny_harness.interaction.renderer)


def test_surface_api_snapshot() -> None:
    assert_snapshot(tiny_harness.interaction.surface)
