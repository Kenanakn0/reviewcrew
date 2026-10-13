"""Shopping cart persistence."""

import base64
import pickle

from flask import request


def load_cart() -> dict:
    raw = request.cookies.get("cart")
    if not raw:
        return {"items": []}
    return pickle.loads(base64.b64decode(raw))


def dump_cart(cart: dict) -> str:
    return base64.b64encode(pickle.dumps(cart)).decode()
