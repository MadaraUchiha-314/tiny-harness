"""``speakable_text``: a reply as text-to-speech should read it (issue-38 R4.1): no
markdown syntax, no code blocks, and at most the provider's 4 096-character input."""

from __future__ import annotations

import pytest

from tiny_harness.harness.media.render import SPEECH_INPUT_LIMIT, speakable_text


@pytest.mark.parametrize(
    ("markdown", "spoken"),
    [
        ("**A** cat.", "A cat."),
        ("# Title\nSome *emphasis* and __strong__ text.", "Title\nSome emphasis and strong text."),
        ("See [the docs](https://example.com/x) now.", "See the docs now."),
        ("![a grey cat](https://example.com/cat.png)", "a grey cat"),
        ("- one\n* two\n+ three\n1. four", "one\ntwo\nthree\nfour"),
        ("> quoted words", "quoted words"),
        ("Run `ls -la` first.", "Run ls -la first."),
        ("Before\n```python\nprint('x')\n```\nAfter", "Before\nAfter"),
        ("a ~~struck~~ word", "a struck word"),
        ("| a | b |\n|---|---|\n| 1 | 2 |", "a b\n1 2"),
        ("line<br>break <b>bold</b>", "line break bold"),
        ("one\n\n\n---\ntwo", "one\ntwo"),
        ("snake_case_name stays", "snake_case_name stays"),
    ],
)
def test_markdown_is_removed(markdown: str, spoken: str) -> None:
    assert speakable_text(markdown) == spoken


def test_the_limit_is_the_providers_input_limit() -> None:
    assert SPEECH_INPUT_LIMIT == 4_096


def test_a_long_reply_is_cut_at_a_word_within_the_limit() -> None:
    text = "word " * 2_000
    spoken = speakable_text(text)
    assert len(spoken) <= SPEECH_INPUT_LIMIT
    assert spoken.endswith("word")
    assert len(spoken) > SPEECH_INPUT_LIMIT - 10


def test_a_long_word_is_cut_hard() -> None:
    assert speakable_text("x" * 5_000) == "x" * SPEECH_INPUT_LIMIT


def test_a_reply_of_only_code_says_nothing() -> None:
    assert speakable_text("```\ncode\n```") == ""
