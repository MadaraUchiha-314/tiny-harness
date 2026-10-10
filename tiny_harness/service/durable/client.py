"""The Temporal client (R19.11): TLS, API key, the Pydantic data converter and tracing."""

from __future__ import annotations

from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter

from tiny_harness.config import TemporalConfig


async def connect(config: TemporalConfig) -> Client:
    """One client, shared by the server and the worker of a process (remote mode only:
    embedded mode connects through ``durable.temporal.EmbeddedTemporal``)."""
    if config.mode != "remote" or config.address is None or config.api_key is None:
        raise ValueError("connect() is for temporal.mode = remote with an address and a key")
    return await Client.connect(
        config.address,
        namespace=config.effective_namespace,
        api_key=config.api_key.get_secret_value(),
        tls=config.tls,
        data_converter=pydantic_data_converter,
        interceptors=[TracingInterceptor()],
    )


__all__ = ["connect", "pydantic_data_converter"]
