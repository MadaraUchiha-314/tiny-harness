"""Feature: model adapters
Requirement: docs/specs/issue-3/requirements.md#R18

Registry tool names (``plugin/server.tool``) cross the provider boundary as names the
provider accepts and come back as the registry names the loop dispatches on.
"""

from __future__ import annotations

from tiny_harness.harness.models.wire_names import MAX_WIRE_LENGTH, WireNames, sanitize
from tiny_harness.harness.tools import ToolDefinition


def tool(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description="d", input_schema={"type": "object"})


def test_wire_names_are_provider_safe_and_decode_to_the_registry_name() -> None:
    """
    Scenario: wire names are provider-safe and decode to the registry name
        Given tools named with a plugin prefix and a server dot
        When the wire names are built
        Then each matches ^[A-Za-z0-9_-]+$ and decodes back to the registry name
    """
    names = WireNames([tool("demo-support/orders.get_order"), tool("ask_participant")])
    wire = names.encode("demo-support/orders.get_order")
    assert wire == "demo-support_orders_get_order"
    assert names.decode(wire) == "demo-support/orders.get_order"
    assert names.encode("ask_participant") == "ask_participant"
    assert sanitize("a b/c.d") == "a_b_c_d"
    assert names.description(tool("demo-support/orders.get_order")) == (
        "d (registry name: demo-support/orders.get_order)"
    )
    assert names.description(tool("ask_participant")) == "d"


def test_colliding_names_get_distinct_wire_names() -> None:
    """
    Scenario: colliding names get distinct wire names
        Given two registry names that sanitize to the same string
        When the wire names are built
        Then they differ and each decodes to its own registry name
    """
    names = WireNames([tool("orders.get_order"), tool("orders/get_order")])
    a, b = names.encode("orders.get_order"), names.encode("orders/get_order")
    assert a == "orders_get_order" and b == "orders_get_order_2"
    assert names.decode(a) == "orders.get_order" and names.decode(b) == "orders/get_order"


def test_long_names_are_cut_to_the_providers_limit_and_stay_distinct() -> None:
    """
    Scenario: long names are cut to the providers' limit and stay distinct
        Given two registry names longer than 64 characters that share a prefix
        When the wire names are built
        Then each is at most 64 characters and decodes to its own registry name
    """
    long_a = "acme-customer-operations-support-plugin/orders.list_open_orders_for_customer"
    long_b = "acme-customer-operations-support-plugin/orders.list_open_orders_for_customers"
    names = WireNames([tool(long_a), tool(long_b)])
    a, b = names.encode(long_a), names.encode(long_b)
    assert len(a) <= MAX_WIRE_LENGTH and len(b) <= MAX_WIRE_LENGTH and a != b
    assert names.decode(a) == long_a and names.decode(b) == long_b


def test_unknown_wire_names_decode_to_themselves() -> None:
    """
    Scenario: unknown wire names decode to themselves
        Given a model that calls a tool that was not offered
        When the name is decoded
        Then it is returned unchanged for the registry to refuse
    """
    assert WireNames().decode("made_up") == "made_up"
