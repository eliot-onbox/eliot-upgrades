"""
Financial forecasting for Tudor's Revolut account.

Projects balance forward 30 days using known recurring expenses
and estimated discretionary spending from historical data.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn

# Known recurring monthly expenses (day of month, description, amount)
# Derived from actual Revolut transaction patterns.
RECURRING = [
    (13, "TF Bank loan", -200.00),
    (14, "Cashper payday loan", -503.18),
    (14, "Apple (subscriptions)", -35.00),
    (15, "Gelbert remittance (PH)", -235.00),
    (15, "Netflix", -19.99),
    (16, "Rent to mother", -400.00),
    (18, "Apple (secondary)", -15.00),
]

# Known income pattern
INCOME = [
    (13, "Salary / ALG I", None),  # Amount unknown — user must set
]


def get_current_balance() -> float | None:
    conn = get_conn()
    row = conn.execute(
        """SELECT balance FROM transactions
           WHERE currency = 'EUR' AND product = 'Current'
           AND balance IS NOT NULL AND state = 'COMPLETED'
           ORDER BY completed_date DESC LIMIT 1""",
    ).fetchone()
    conn.close()
    return row["balance"] if row else None


def get_daily_discretionary(days: int = 14) -> float:
    """Average daily discretionary spending (Wolt, food, compute, etc).
    Excludes recurring fixed costs which are modeled separately."""
    conn = get_conn()
    row = conn.execute(
        """SELECT SUM(amount) as total, COUNT(DISTINCT DATE(completed_date)) as days
           FROM transactions
           WHERE currency = 'EUR' AND product = 'Current'
           AND amount < 0 AND state = 'COMPLETED'
           AND category NOT IN (
               'savings_transfer', 'currency_exchange',
               'loan_payment', 'remittance', 'personal_transfer',
               'subscriptions'
           )
           AND completed_date >= date('now', ? || ' days')""",
        (f"-{days}",),
    ).fetchone()
    conn.close()

    if row["days"] and row["total"]:
        return row["total"] / row["days"]  # negative number
    return -30.0  # fallback estimate


def forecast(balance: float | None = None, days: int = 30,
             expected_income: float | None = None) -> dict:
    """Project balance forward.

    Returns dict with daily projections, zero-day, and summary.
    """
    if balance is None:
        balance = get_current_balance()
    if balance is None:
        return {"error": "No balance data available"}

    daily_disc = get_daily_discretionary()
    today = datetime.now().date()

    projections = []
    running = balance
    zero_day = None

    for i in range(days + 1):
        day = today + timedelta(days=i)
        day_num = day.day
        events = []

        if i == 0:
            projections.append({
                "date": day, "balance": running,
                "events": ["current"], "delta": 0,
            })
            continue

        delta = daily_disc  # baseline discretionary spending

        # Check for recurring expenses on this day
        for rec_day, desc, amount in RECURRING:
            if day_num == rec_day:
                delta += amount
                events.append(f"{desc}: {amount:.0f}")

        # Check for expected income
        for inc_day, desc, amount in INCOME:
            if day_num == inc_day and expected_income:
                delta += expected_income
                events.append(f"{desc}: +{expected_income:.0f}")

        running += delta

        if running <= 0 and zero_day is None:
            zero_day = day

        projections.append({
            "date": day, "balance": running,
            "events": events, "delta": delta,
        })

    return {
        "start_balance": balance,
        "daily_discretionary": daily_disc,
        "zero_day": zero_day,
        "days_until_zero": (zero_day - today).days if zero_day else None,
        "end_balance": running,
        "expected_income": expected_income,
        "projections": projections,
    }


def print_forecast(result: dict):
    if "error" in result:
        print(f"  Error: {result['error']}")
        return

    print(f"\n  Starting balance: EUR {result['start_balance']:.2f}")
    print(f"  Daily discretionary: EUR {result['daily_discretionary']:.2f}/day")
    if result["expected_income"]:
        print(f"  Expected income: EUR {result['expected_income']:.2f} (13th)")
    else:
        print(f"  Expected income: UNKNOWN (set with --income)")
    print()

    # Print projection table
    print(f"  {'Date':<12s} {'Balance':>10s}  {'Delta':>8s}  Events")
    print(f"  {'-'*12} {'-'*10}  {'-'*8}  {'-'*30}")

    for p in result["projections"]:
        date_str = p["date"].strftime("%a %b %d")
        bal = p["balance"]
        delta_str = f"{p['delta']:+.0f}" if p["delta"] != 0 else ""
        events_str = ", ".join(p["events"]) if p["events"] else ""

        # Highlight danger zone
        marker = ""
        if bal <= 0:
            marker = " << ZERO"
        elif bal < 50:
            marker = " << LOW"

        print(f"  {date_str:<12s} {bal:>10.2f}  {delta_str:>8s}  {events_str}{marker}")

    print()
    if result["zero_day"]:
        print(f"  ** Balance hits zero: {result['zero_day'].strftime('%A %B %d')} "
              f"({result['days_until_zero']} days) **")
    else:
        print(f"  Balance stays positive through forecast period.")
        print(f"  End balance: EUR {result['end_balance']:.2f}")


if __name__ == "__main__":
    income = None
    for i, arg in enumerate(sys.argv):
        if arg == "--income" and i + 1 < len(sys.argv):
            income = float(sys.argv[i + 1])
        elif arg == "--balance" and i + 1 < len(sys.argv):
            balance = float(sys.argv[i + 1])

    result = forecast(expected_income=income)
    print_forecast(result)
