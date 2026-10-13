"""Profile endpoint."""

import requests
from fastapi import APIRouter

router = APIRouter()
IDENTITY_URL = "https://identity.internal/users"


@router.get("/profiles/{user_id}")
async def get_profile(user_id: int) -> dict:
    response = requests.get(f"{IDENTITY_URL}/{user_id}", timeout=5)
    response.raise_for_status()
    return response.json()
