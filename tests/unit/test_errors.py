"""The error hierarchy (design.md § Error handling).

One code per class, and a detail map that never carries a secret.
"""

import inspect

import tiny_harness.errors as errors
from tiny_harness.errors import (
    AbortReason,
    ConfigError,
    EntityNotFoundError,
    HookAbort,
    RetryableProviderError,
    TinyHarnessError,
    ToolArgumentError,
)


def _subclasses() -> list[type[TinyHarnessError]]:
    return [
        obj
        for _, obj in inspect.getmembers(errors, inspect.isclass)
        if issubclass(obj, TinyHarnessError) and obj is not TinyHarnessError
    ]


def test_every_error_has_a_unique_code() -> None:
    codes = [cls.code for cls in _subclasses()]
    assert len(codes) >= 18
    assert len(codes) == len(set(codes))
    assert all("." in code for code in codes)


def test_detail_is_a_string_map_and_renders_in_str() -> None:
    err = EntityNotFoundError("no such entity", kind="tool", id="orders.get_order")
    assert err.code == "entity.not_found"
    assert err.detail == {"kind": "tool", "id": "orders.get_order"}
    assert "entity.not_found" in str(err) and "orders.get_order" in str(err)
    assert err.to_record() == {
        "code": "entity.not_found",
        "message": "no such entity",
        "detail": {"kind": "tool", "id": "orders.get_order"},
    }


def test_specialised_errors_carry_their_named_fields() -> None:
    assert ConfigError("missing", variable="OPENAI_API_KEY").variable == "OPENAI_API_KEY"
    assert HookAbort("refused", reason=AbortReason.POLICY).reason is AbortReason.POLICY
    err = RetryableProviderError("rate limited", provider="openai", status=429)
    assert err.provider == "openai" and err.status == 429 and err.retryable
    assert ToolArgumentError("bad args", validation="'order_id' is required").validation


def test_detail_keys_never_look_like_secrets() -> None:
    for cls in _subclasses():
        fields = inspect.signature(cls.__init__).parameters
        for name in fields:
            assert not any(s in name.lower() for s in ("secret", "token", "password", "key")), (
                f"{cls.__name__} takes a credential-shaped field {name}"
            )
