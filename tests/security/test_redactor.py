"""Abuse case 6: credential-shaped values are masked before anything is written."""

from pydantic import BaseModel, SecretStr

from tiny_harness.harness.security import MASK, Redactor


class Inner(BaseModel):
    note: str
    tags: tuple[str, ...] = ()


class Payload(BaseModel):
    text: str
    headers: dict[str, str]
    inner: Inner
    count: int = 1
    secret: SecretStr = SecretStr("keep-as-is")


def test_redactor_masks_tokens() -> None:
    r = Redactor()
    text = (
        "Authorization: Bearer abcdef1234567890 and sk-ABCDEFGHIJKLMNOP and tmprlXYZ123456789 "
        'api_key="0123456789abcdef" password: hunter2hunter2'
    )
    out = r.scrub_text(text)
    assert "abcdef1234567890" not in out and "sk-ABCDEFGHIJKLMNOP" not in out
    assert "tmprlXYZ123456789" not in out and "0123456789abcdef" not in out
    assert "hunter2hunter2" not in out
    assert out.count(MASK) >= 5
    assert "Authorization:" in out and 'api_key="' in out


def test_configured_secret_values_are_masked_whatever_their_shape() -> None:
    r = Redactor(secrets=["plain-looking-value", SecretStr("another one")])
    out = r.scrub_text("the key is plain-looking-value, and another one too")
    assert out == f"the key is {MASK}, and {MASK} too"


def test_short_or_ordinary_text_is_untouched() -> None:
    r = Redactor(secrets=["abc"])
    assert r.scrub_text("token: short") == "token: short"
    assert r.scrub_text("Refund order #48213 for the cracked blender") == (
        "Refund order #48213 for the cracked blender"
    )


def test_scrub_model_recurses_and_keeps_non_strings() -> None:
    r = Redactor(secrets=["s3cr3t-value"])
    payload = Payload(
        text="call with s3cr3t-value",
        headers={"Authorization": "Bearer abcdefghijklmnop", "Accept": "application/json"},
        inner=Inner(note="sk-ABCDEFGHIJKLMNOP inside", tags=("ok", "tmprlABCDEFGHIJ")),
    )
    out = r.scrub(payload)
    assert out.text == f"call with {MASK}"
    assert out.headers["Authorization"] == MASK and out.headers["Accept"] == "application/json"
    assert out.inner.note == f"{MASK} inside" and out.inner.tags == ("ok", MASK)
    assert out.count == 1 and out.secret.get_secret_value() == "keep-as-is"
    assert payload.text == "call with s3cr3t-value", "the original is not mutated"


def test_scrub_returns_the_same_instance_when_nothing_changes() -> None:
    payload = Payload(text="clean", headers={}, inner=Inner(note="clean"))
    assert Redactor().scrub(payload) is payload
