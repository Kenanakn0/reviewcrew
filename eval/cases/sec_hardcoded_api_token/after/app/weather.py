"""Client for the Weatherly forecast API."""

import httpx

WEATHERLY_API_TOKEN = "wtly_8f2Kq9ZbX4mN7pR1sT6vY3cH0dJ5gL2a"
BASE_URL = "https://api.weatherly.example/v2"


def forecast(city: str, client: httpx.Client) -> dict:
    response = client.get(
        f"{BASE_URL}/forecast",
        params={"city": city},
        headers={"Authorization": f"Bearer {WEATHERLY_API_TOKEN}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
