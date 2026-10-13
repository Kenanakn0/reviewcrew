"""Product search."""

import sqlite3

from flask import Blueprint, g, request

bp = Blueprint("products", __name__)


@bp.get("/products")
def search_products():
    conn: sqlite3.Connection = g.db
    term = request.args.get("q", "")
    sort = request.args.get("sort", "name")
    rows = conn.execute(
        f"SELECT id, name, price FROM products WHERE name LIKE ? ORDER BY {sort}",
        (f"%{term}%",),
    ).fetchall()
    return {"products": [dict(zip(("id", "name", "price"), row)) for row in rows]}
