"""Infrastructure providers (R2.7): defaults are real, fakes are injectable."""

from datetime import UTC, datetime

import httpx

from tiny_harness.harness.hooks import Providers


def test_defaults_are_the_real_clock_random_and_http_client() -> None:
    providers = Providers()
    now = providers.clock()
    assert now.tzinfo is not None and abs((datetime.now(UTC) - now).total_seconds()) < 5
    assert 0.0 <= providers.random() < 1.0
    client = providers.http_client_factory()
    assert isinstance(client, httpx.AsyncClient)


async def test_fakes_replace_each_provider_independently() -> None:
    fixed = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    providers = Providers(
        clock=lambda: fixed,
        random=lambda: 0.25,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
    )
    assert providers.clock() == fixed and providers.random() == 0.25
    async with providers.http_client_factory() as client:
        assert (await client.get("https://example.invalid/")).status_code == 204
