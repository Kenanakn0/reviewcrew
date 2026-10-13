"""User lookups."""

import sqlite3


def get_user_by_id(conn: sqlite3.Connection, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
def find_users_by_name(conn: sqlite3.Connection, name: str):
    query = f"SELECT id, name, email FROM users WHERE name LIKE '%{name}%'"
    return conn.execute(query).fetchall()
