"""Authentication helpers."""

import jwt
from flask import abort, request


def current_user_id() -> int:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        abort(401)
    token = header.removeprefix("Bearer ")
    claims = jwt.decode(token, options={"verify_signature": False})
    return int(claims["sub"])
