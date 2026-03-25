"""Shared database setup for Eliot's context system."""

import sqlite3
import os

DB_PATH = os.environ.get("ELIOT_DB", "/home/eliot/.openclaw/workspace/data/eliot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            source TEXT DEFAULT 'iphone',
            processed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            product TEXT NOT NULL,
            started_date TEXT,
            completed_date TEXT,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            fee REAL DEFAULT 0,
            currency TEXT NOT NULL,
            state TEXT NOT NULL,
            balance REAL,
            category TEXT,
            source_file TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category);
        CREATE INDEX IF NOT EXISTS idx_tx_completed ON transactions(completed_date);
        CREATE INDEX IF NOT EXISTS idx_tx_currency ON transactions(currency);
    """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
