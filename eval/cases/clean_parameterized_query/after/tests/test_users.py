import sqlite3

import pytest

from app.users import get_user_by_email


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    conn.execute("INSERT INTO users (name, email) VALUES ('Ada', 'ada@example.com')")
    return conn


def test_finds_user_case_insensitively(conn):
    assert get_user_by_email(conn, "ADA@example.com")[1] == "Ada"


def test_unknown_email_returns_none(conn):
    assert get_user_by_email(conn, "nobody@example.com") is None
