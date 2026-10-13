"""Geocoding of addresses."""

import httpx

GEOCODER = "https://geo.example.com/v1/search"


def geocode_all(addresses: list[str]) -> list[tuple[float, float]]:
    points = []
    for address in addresses:
        with httpx.Client() as client:
            data = client.get(GEOCODER, params={"q": address}, timeout=5).json()
        points.append((data["lat"], data["lon"]))
    return points
