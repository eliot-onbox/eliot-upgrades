#!/usr/bin/env python3
"""
Heartbeat context summary. Outputs a one-liner about Tudor's current state.
Outputs nothing if there's nothing worth saying.

Called from heartbeat checks. Reads tudor-state.json and financial data.
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn, DB_PATH

STATE_FILE = "/home/eliot/workspace/data/tudor-state.json"


def get_state():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE) as f:
        return json.load(f)


def get_balance_info():
    if not os.path.exists(DB_PATH):
        return None
    conn = get_conn()

    last_balance = conn.execute(
        """SELECT balance FROM transactions
           WHERE currency = 'EUR' AND product = 'Current'
           AND balance IS NOT NULL AND state = 'COMPLETED'
           ORDER BY completed_date DESC LIMIT 1""",
    ).fetchone()

    if not last_balance:
        conn.close()
        return None

    balance = last_balance["balance"]

    burn = conn.execute(
        """SELECT SUM(amount) as total, COUNT(DISTINCT DATE(completed_date)) as days
           FROM transactions
           WHERE currency = 'EUR' AND product = 'Current'
           AND amount < 0 AND state = 'COMPLETED'
           AND category NOT IN ('savings_transfer', 'currency_exchange', 'loan_payment', 'remittance')
           AND completed_date >= date('now', '-14 days')""",
    ).fetchone()
    conn.close()

    daily_burn = abs(burn["total"] / burn["days"]) if burn["days"] and burn["total"] else 0
    days_left = balance / daily_burn if daily_burn > 0 else None

    return {"balance": balance, "daily_burn": daily_burn, "days_left": days_left}


def main():
    parts = []
    state = get_state()

    if state:
        # Location — only if reasonably fresh (last 12 hours)
        loc = state.get("location")
        if loc:
            age = datetime.now() - datetime.fromisoformat(loc["updated_at"])
            if age < timedelta(hours=12):
                if loc["event"] == "left":
                    parts.append(f"left {loc['name']}")
                elif loc["event"] == "arrived":
                    parts.append(f"at {loc['name']}")

        # Battery — only if low
        bat = state.get("battery")
        if bat and bat.get("level") is not None:
            age = datetime.now() - datetime.fromisoformat(bat["updated_at"])
            if age < timedelta(hours=3):
                if bat["level"] <= 20 and not bat.get("charging"):
                    parts.append(f"battery {bat['level']}%")

        # Focus — only if active
        focus = state.get("focus")
        if focus and focus.get("active"):
            age = datetime.now() - datetime.fromisoformat(focus["updated_at"])
            if age < timedelta(hours=12):
                parts.append(f"{focus['mode']} mode")

    # Finance — only if concerning
    fin = get_balance_info()
    if fin:
        if fin["days_left"] is not None and fin["days_left"] <= 5:
            parts.append(f"EUR {fin['balance']:.0f}, ~{fin['days_left']:.0f}d until zero")
        elif fin["balance"] < 50:
            parts.append(f"EUR {fin['balance']:.0f}")

    if not parts:
        return

    print("Tudor: " + ", ".join(parts) + ".")


if __name__ == "__main__":
    main()
