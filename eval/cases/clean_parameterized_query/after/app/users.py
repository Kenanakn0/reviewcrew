"""User lookups."""

import sqlite3


def get_user_by_id(conn: sqlite3.Connection, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
def get_user_by_email(conn: sqlite3.Connection, email: str):
    return conn.execute(
        "SELECT id, name, email FROM users WHERE email = ?", (email.lower(),)
    ).fetchone()
