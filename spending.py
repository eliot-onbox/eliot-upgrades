#!/usr/bin/env python3
"""
Parse Revolut CSV exports and load into SQLite with auto-categorization.

Usage:
  python3 spending.py /path/to/revolut.csv
  python3 spending.py  # uses default path
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn, init_db
from categories import categorize

DEFAULT_CSV = os.path.expanduser(
    "~/workspace/data/finance/revolut-2026-02-01-to-2026-03-17.csv"
)


def parse_and_load(csv_path: str) -> dict:
    """Parse a Revolut CSV and insert transactions into the database.

    Returns stats about what was loaded.
    """
    init_db()
    conn = get_conn()

    # Check how many rows already exist from this file to avoid duplicates
    source_file = os.path.basename(csv_path)
    existing = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE source_file = ?", (source_file,)
    ).fetchone()[0]

    if existing > 0:
        # Wipe and reload from this file (idempotent reimport)
        conn.execute("DELETE FROM transactions WHERE source_file = ?", (source_file,))
        conn.commit()

    inserted = 0
    categories_seen = {}

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = categorize(row["Description"])
            amount = float(row["Amount"])
            fee = float(row["Fee"]) if row["Fee"] else 0.0
            balance = float(row["Balance"]) if row["Balance"] else None

            conn.execute(
                """INSERT INTO transactions
                   (type, product, started_date, completed_date, description,
                    amount, fee, currency, state, balance, category, source_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["Type"],
                    row["Product"],
                    row["Started Date"],
                    row["Completed Date"] or None,
                    row["Description"],
                    amount,
                    fee,
                    row["Currency"],
                    row["State"],
                    balance,
                    category,
                    source_file,
                ),
            )
            inserted += 1
            categories_seen[category] = categories_seen.get(category, 0) + 1

    conn.commit()
    conn.close()
    return {
        "file": csv_path,
        "rows_inserted": inserted,
        "categories": categories_seen,
    }


def spending_summary(currency: str = "EUR", product: str = "Current") -> dict:
    """Generate a spending summary from the database."""
    conn = get_conn()

    # Total income vs spending
    income = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) FROM transactions
           WHERE currency = ? AND product = ? AND amount > 0
           AND state = 'COMPLETED'
           AND category NOT IN ('savings_transfer', 'currency_exchange')""",
        (currency, product),
    ).fetchone()[0]

    spending = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) FROM transactions
           WHERE currency = ? AND product = ? AND amount < 0
           AND state = 'COMPLETED'
           AND category NOT IN ('savings_transfer', 'currency_exchange')""",
        (currency, product),
    ).fetchone()[0]

    # By category (spending only, exclude noise)
    rows = conn.execute(
        """SELECT category, SUM(amount) as total, COUNT(*) as count
           FROM transactions
           WHERE currency = ? AND product = ? AND amount < 0
           AND state = 'COMPLETED'
           AND category NOT IN ('savings_transfer', 'currency_exchange')
           GROUP BY category
           ORDER BY total ASC""",
        (currency, product),
    ).fetchall()

    by_category = [
        {"category": r["category"], "total": r["total"], "count": r["count"]}
        for r in rows
    ]

    # Current balance (last known)
    last_balance = conn.execute(
        """SELECT balance FROM transactions
           WHERE currency = ? AND product = ? AND balance IS NOT NULL
           AND state = 'COMPLETED'
           ORDER BY completed_date DESC LIMIT 1""",
        (currency, product),
    ).fetchone()

    # Large transactions (> 100 EUR)
    large = conn.execute(
        """SELECT description, amount, completed_date, category
           FROM transactions
           WHERE currency = ? AND product = ? AND amount < -100
           AND state = 'COMPLETED'
           ORDER BY amount ASC""",
        (currency, product),
    ).fetchall()

    # Date range
    date_range = conn.execute(
        """SELECT MIN(started_date) as first, MAX(started_date) as last
           FROM transactions
           WHERE currency = ? AND product = ?""",
        (currency, product),
    ).fetchone()

    conn.close()

    return {
        "currency": currency,
        "product": product,
        "period": {"from": date_range["first"], "to": date_range["last"]},
        "income": income,
        "spending": spending,
        "net": income + spending,
        "current_balance": last_balance["balance"] if last_balance else None,
        "by_category": by_category,
        "large_transactions": [
            {
                "description": r["description"],
                "amount": r["amount"],
                "date": r["completed_date"],
                "category": r["category"],
            }
            for r in large
        ],
    }


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        sys.exit(1)

    result = parse_and_load(csv_path)
    print(f"Loaded {result['rows_inserted']} transactions from {result['file']}")
    print(f"Categories: {result['categories']}")
    print()

    # Print EUR summary
    summary = spending_summary("EUR", "Current")
    print(f"=== EUR Current Account ({summary['period']['from'][:10]} to {summary['period']['to'][:10]}) ===")
    print(f"  Income:   +{summary['income']:>10.2f} EUR")
    print(f"  Spending:  {summary['spending']:>10.2f} EUR")
    print(f"  Net:       {summary['net']:>10.2f} EUR")
    print(f"  Balance:   {summary['current_balance']:>10.2f} EUR")
    print()
    print("  Spending by category:")
    from categories import CATEGORY_LABELS
    for cat in summary["by_category"]:
        label = CATEGORY_LABELS.get(cat["category"], cat["category"])
        print(f"    {label:<25s} {cat['total']:>10.2f} EUR  ({cat['count']} txns)")

    if summary["large_transactions"]:
        print()
        print("  Transactions over 100 EUR:")
        for tx in summary["large_transactions"]:
            print(f"    {tx['date'][:10]}  {tx['amount']:>10.2f} EUR  {tx['description']}")
