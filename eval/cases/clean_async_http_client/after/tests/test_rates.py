import httpx
import pytest

from app.rates import fetch_rates


@pytest.mark.asyncio
async def test_fetches_each_currency_once():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["base"])
        return httpx.Response(200, json={"rate": 1.5})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rates = await fetch_rates(client, ["EUR", "USD"])

    assert rates == {"EUR": 1.5, "USD": 1.5}
    assert sorted(seen) == ["EUR", "USD"]


@pytest.mark.asyncio
async def test_http_errors_propagate():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_rates(client, ["EUR"])
