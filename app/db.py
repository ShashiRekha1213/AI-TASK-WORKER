"""SQLite storage for the simulated internal payables system."""

import sqlite3
from config import DB_PATH


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS payables(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor TEXT NOT NULL, invoice_no TEXT NOT NULL,
            amount REAL NOT NULL, due_date TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


def reset():
    DB_PATH.unlink(missing_ok=True)
    init()


def add(vendor, invoice_no, amount, due_date):
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO payables(vendor,invoice_no,amount,due_date) VALUES(?,?,?,?)",
            (vendor, invoice_no, amount, due_date),
        )
        return cur.lastrowid


def all_rows():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM payables ORDER BY id")]
