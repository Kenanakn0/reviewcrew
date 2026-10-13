"""Deliver events to partner endpoints."""

import requests


def deliver(url: str, event: dict) -> bool:
    response = requests.post(url, json=event, timeout=10, verify=False)
    return response.ok
