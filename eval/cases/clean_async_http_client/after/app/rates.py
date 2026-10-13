"""Exchange rates from the rates service."""

import asyncio

import httpx

RATES_URL = "https://rates.internal/v1/latest"


async def fetch_rates(client: httpx.AsyncClient, currencies: list[str]) -> dict[str, float]:
    async def one(currency: str) -> tuple[str, float]:
        response = await client.get(RATES_URL, params={"base": currency}, timeout=5)
        response.raise_for_status()
        return currency, float(response.json()["rate"])

    pairs = await asyncio.gather(*(one(c) for c in currencies))
    return dict(pairs)
