"""CSV export of recent events."""

import csv
import io
import sqlite3
from datetime import datetime, timedelta


def export_last_week(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT id, kind, created_at FROM events").fetchall()
    cutoff = datetime.now() - timedelta(days=7)
    recent = [r for r in rows if datetime.fromisoformat(r[2]) >= cutoff]
    out = io.StringIO()
    csv.writer(out).writerows(recent)
    return out.getvalue()
