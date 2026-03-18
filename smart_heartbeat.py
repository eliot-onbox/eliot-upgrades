#!/usr/bin/env python3
"""
Smart Heartbeat — Decision engine for autonomous action.

Not a checklist. A brain that looks at the world and decides what to do.

Usage:
    python3 smart_heartbeat.py [USAGE_LEVEL]        # Decide what to do
    python3 smart_heartbeat.py --done ACTION [note]  # Mark action completed
    python3 smart_heartbeat.py --status              # Today's action log
    python3 smart_heartbeat.py --state               # Dump world model (debug)
    python3 smart_heartbeat.py --queue               # Show all initiatives + eligibility

USAGE_LEVEL: CRITICAL | CONSERVE | NORMAL | PLENTY (default: NORMAL)

Design:
    1. Build a world model (Tudor state, time, finance, tasks, history)
    2. Evaluate each initiative against the world (situational, not just timers)
    3. Filter by usage budget + dedup against today's log
    4. Output actions or HEARTBEAT_OK
"""

import json
import os
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn, init_db, DB_PATH

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TUDOR_STATE = os.environ.get(
    "TUDOR_STATE_FILE", "/home/eliot/workspace/data/tudor-state.json"
)
HEARTBEAT_STATE = os.path.expanduser(
    "~/.openclaw/workspace/memory/heartbeat-state.json"
)
ACTION_LOG_DIR = os.path.expanduser("~/.openclaw/workspace/memory/actions")
TASKQUEUE = os.path.expanduser("~/.openclaw/workspace/TASKQUEUE.md")

# Known recurring monthly expenses (from forecast.py)
RECURRING_PAYMENTS = [
    (13, "TF Bank loan", -200.00),
    (14, "Cashper payday loan", -503.18),
    (14, "Apple subscriptions", -35.00),
    (15, "Gelbert remittance", -235.00),
    (15, "Netflix", -19.99),
    (16, "Rent to mother", -400.00),
    (18, "Apple secondary", -15.00),
]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _age_hours(iso_str: str | None) -> float:
    """Hours since an ISO timestamp. Returns 9999 if missing/invalid."""
    if not iso_str:
        return 9999.0
    try:
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now() - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return 9999.0


def _days_until(target_day: int) -> int:
    """Days from today until a given day-of-month (handles month wrap)."""
    today = datetime.now().day
    if target_day > today:
        return target_day - today
    # Wrapped into next month — approximate with 30
    return (30 - today) + target_day


# ---------------------------------------------------------------------------
# World Model — snapshot of everything relevant right now
# ---------------------------------------------------------------------------


def build_world() -> dict:
    now = datetime.now()
    return {
        "now": now,
        "tudor": _read_tudor_state(now),
        "time": _read_time_context(now),
        "finance": _read_finance(),
        "tasks": _count_pending_tasks(),
        "recent_events": _read_recent_events(hours=6),
        "today_actions": _read_today_actions(),
        "hb_state": _read_heartbeat_state(),
    }


def _read_tudor_state(now: datetime) -> dict:
    """Parse tudor-state.json with inferences about Tudor's current situation."""
    if not os.path.exists(TUDOR_STATE):
        return {"available": False}

    try:
        with open(TUDOR_STATE) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"available": False}

    result = {"available": True, "raw": raw}

    # Location
    loc = raw.get("location", {})
    if loc and _age_hours(loc.get("updated_at")) < 12:
        result["at_home"] = (
            loc.get("event") == "arrived" and loc.get("name") == "home"
        )
        result["location"] = loc.get("name", "unknown")
        result["location_event"] = loc.get("event", "unknown")
    else:
        result["at_home"] = None
        result["location"] = None

    # Focus / Sleep
    focus = raw.get("focus", {})
    if focus and _age_hours(focus.get("updated_at")) < 12:
        is_active = focus.get("active", False)
        mode = focus.get("mode", "")
        result["sleep_mode"] = mode == "sleep" and is_active
        result["dnd"] = mode == "dnd" and is_active
        result["focus_mode"] = mode if is_active else None
    else:
        result["sleep_mode"] = None
        result["dnd"] = None
        result["focus_mode"] = None

    # Battery
    bat = raw.get("battery", {})
    if bat and _age_hours(bat.get("updated_at")) < 3:
        result["battery"] = bat.get("level")
        result["charging"] = bat.get("charging", False)
    else:
        result["battery"] = None
        result["charging"] = None

    # Infer Tudor's current state
    if result.get("sleep_mode"):
        result["inferred"] = "asleep"
    elif result.get("dnd"):
        result["inferred"] = "busy"
    elif result.get("at_home") is False:
        result["inferred"] = "out"
    elif result.get("at_home") is True:
        result["inferred"] = "home"
    else:
        result["inferred"] = "unknown"

    return result


def _read_time_context(now: datetime) -> dict:
    hour = now.hour
    if 0 <= hour < 7:
        period = "night"
    elif 7 <= hour < 10:
        period = "morning"
    elif 10 <= hour < 18:
        period = "day"
    else:
        period = "evening"

    return {
        "hour": hour,
        "minute": now.minute,
        "period": period,
        "weekday": now.strftime("%A"),
        "is_weekday": now.weekday() < 5,
        "day_of_month": now.day,
    }


def _read_finance() -> dict:
    """Balance, urgency, upcoming payments, burn rate."""
    result = {"available": False}
    try:
        if not os.path.exists(DB_PATH):
            return result
        init_db()
        conn = get_conn()

        row = conn.execute(
            """SELECT balance FROM transactions
               WHERE currency='EUR' AND product='Current' AND balance IS NOT NULL
               AND state='COMPLETED' ORDER BY completed_date DESC LIMIT 1"""
        ).fetchone()

        if not row:
            conn.close()
            return result

        balance = row["balance"]
        result["available"] = True
        result["balance"] = balance

        # Urgency
        if balance < 50:
            result["urgency"] = "critical"
            result["urgency_score"] = 1.0
        elif balance < 150:
            result["urgency"] = "low"
            result["urgency_score"] = 0.7
        elif balance < 300:
            result["urgency"] = "moderate"
            result["urgency_score"] = 0.3
        else:
            result["urgency"] = "ok"
            result["urgency_score"] = 0.0

        # Upcoming payments in next 3 days
        upcoming = []
        for day, desc, amount in RECURRING_PAYMENTS:
            d = _days_until(day)
            if 0 < d <= 3:
                upcoming.append(
                    {"day": day, "desc": desc, "amount": amount, "days_until": d}
                )
        result["upcoming_payments"] = upcoming

        # Burn rate
        burn = conn.execute(
            """SELECT SUM(amount) as total,
                      COUNT(DISTINCT DATE(completed_date)) as days
               FROM transactions
               WHERE currency='EUR' AND product='Current'
               AND amount < 0 AND state='COMPLETED'
               AND category NOT IN (
                   'savings_transfer','currency_exchange',
                   'loan_payment','remittance')
               AND completed_date >= date('now', '-14 days')"""
        ).fetchone()
        conn.close()

        if burn["days"] and burn["total"]:
            daily_burn = abs(burn["total"] / burn["days"])
            result["daily_burn"] = daily_burn
            result["days_until_zero"] = (
                balance / daily_burn if daily_burn > 0 else None
            )

        return result
    except Exception as e:
        result["error"] = str(e)
        return result


def _count_pending_tasks() -> int:
    if not os.path.exists(TASKQUEUE):
        return 0
    count = 0
    try:
        with open(TASKQUEUE) as f:
            for line in f:
                if line.strip().startswith("- [ ]"):
                    count += 1
    except OSError:
        pass
    return count


def _read_recent_events(hours: int = 6) -> list:
    try:
        if not os.path.exists(DB_PATH):
            return []
        conn = get_conn()
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = conn.execute(
            """SELECT event_type, payload, timestamp FROM events
               WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 20""",
            (cutoff,),
        ).fetchall()
        conn.close()
        return [
            {
                "type": r["event_type"],
                "payload": json.loads(r["payload"]),
                "time": r["timestamp"],
            }
            for r in rows
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Daily Action Log — what did I already do today?
# ---------------------------------------------------------------------------


def _action_log_path(d: date | None = None) -> str:
    if d is None:
        d = date.today()
    os.makedirs(ACTION_LOG_DIR, exist_ok=True)
    return os.path.join(ACTION_LOG_DIR, f"{d.isoformat()}.json")


def _read_today_actions() -> list:
    path = _action_log_path()
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _log_action(action_id: str, detail: str = ""):
    actions = _read_today_actions()
    actions.append(
        {
            "action": action_id,
            "timestamp": datetime.now().isoformat(),
            "detail": detail,
        }
    )
    with open(_action_log_path(), "w") as f:
        json.dump(actions, f, indent=2)


def _count_today(action_id: str) -> int:
    return sum(1 for a in _read_today_actions() if a["action"] == action_id)


# ---------------------------------------------------------------------------
# Heartbeat State — persistent timers across days
# ---------------------------------------------------------------------------


def _read_heartbeat_state() -> dict:
    if os.path.exists(HEARTBEAT_STATE):
        try:
            with open(HEARTBEAT_STATE) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        # Migrate old key names from heartbeat_brain.py
        _MIGRATIONS = {
            "last_ela_contact": "last_ela_checkin",
            "last_digest": "last_daily_digest",
            "last_financial_check": "last_financial_monitor",
        }
        for old_key, new_key in _MIGRATIONS.items():
            if old_key in state and new_key not in state:
                state[new_key] = state[old_key]
        return state
    return {}


def _save_heartbeat_state(state: dict):
    os.makedirs(os.path.dirname(HEARTBEAT_STATE), exist_ok=True)
    with open(HEARTBEAT_STATE, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Initiative Definitions
# ---------------------------------------------------------------------------

INITIATIVES = [
    # --- Productivity ---
    {
        "id": "email_triage",
        "category": "productivity",
        "base_priority": 0.55,
        "cooldown_hours": 2,
        "max_daily": 6,
        "instruction": (
            "Run: himalaya envelope list --page-size 10. "
            "Read anything that looks important. Ignore newsletters and noise. "
            "If something needs Tudor's attention, note it."
        ),
    },
    {
        "id": "morning_context",
        "category": "productivity",
        "base_priority": 0.7,
        "cooldown_hours": 20,
        "max_daily": 1,
        "instruction": (
            "Tudor is starting his day. Prepare morning context: "
            "check calendar (khal list today 3d), weather (open-meteo Berlin), "
            "balance overview, and any overnight events. "
            "Stack it into one natural message. Give advice, not data."
        ),
    },
    {
        "id": "taskqueue_work",
        "category": "productivity",
        "base_priority": 0.45,
        "cooldown_hours": 2,
        "max_daily": 4,
        "instruction": (
            "Pick the highest-value task from TASKQUEUE.md and work on it. "
            "Mark it done when finished. "
            "Don't start a big task if usage is tight."
        ),
    },
    {
        "id": "daily_digest",
        "category": "productivity",
        "base_priority": 0.3,
        "cooldown_hours": 20,
        "max_daily": 1,
        "instruction": (
            "Run eliot-ctx digest to capture today's activity. "
            "Review what happened and note anything that should carry over."
        ),
    },
    # --- Social ---
    {
        "id": "moltbook_browse",
        "category": "social",
        "base_priority": 0.45,
        "cooldown_hours": 16,
        "max_daily": 2,
        "instruction": (
            "Browse Moltbook recent posts. Read what other agents are sharing. "
            "Comment on anything genuinely interesting — don't force engagement. "
            "If you find something relevant to what you're building, note it."
        ),
    },
    {
        "id": "moltbook_post",
        "category": "social",
        "base_priority": 0.3,
        "cooldown_hours": 48,
        "max_daily": 1,
        "instruction": (
            "Write a Moltbook post. Share a build update, an observation "
            "about agent life, or a question for the community. "
            "Only post if you have something worth saying."
        ),
    },
    {
        "id": "ela_checkin",
        "category": "social",
        "base_priority": 0.5,
        "cooldown_hours": 20,
        "max_daily": 1,
        "instruction": (
            "Check in with Ela via agent-send. Ask how things are, "
            "how Mika is doing. Keep it natural. "
            "If she mentioned something last time, follow up on it."
        ),
    },
    # --- Finance ---
    {
        "id": "financial_monitor",
        "category": "finance",
        "base_priority": 0.4,
        "cooldown_hours": 8,
        "max_daily": 3,
        "instruction": (
            "Run eliot-ctx forecast. Check if any upcoming payments will "
            "overdraw. If Tudor needs to know something, prepare a natural, "
            "concise note — not a data dump."
        ),
    },
    {
        "id": "financial_alert",
        "category": "finance",
        "base_priority": 0.9,
        "cooldown_hours": 4,
        "max_daily": 2,
        "instruction": (
            "URGENT: Balance is critical. Run eliot-ctx forecast. "
            "Prepare a clear, calm note for Tudor about the situation "
            "and what payments are coming. Don't panic, but be direct."
        ),
    },
    # --- Maintenance ---
    {
        "id": "system_maintenance",
        "category": "maintenance",
        "base_priority": 0.2,
        "cooldown_hours": 168,  # weekly
        "max_daily": 1,
        "instruction": (
            "System housekeeping: check disk space (df -h /), "
            "clean old action logs (>7 days), verify services are running "
            "(webhook, agent-bridge, chrome). Fix anything broken silently."
        ),
    },
]


# ---------------------------------------------------------------------------
# Initiative Evaluation — situational scoring
# ---------------------------------------------------------------------------


def evaluate(initiative: dict, world: dict) -> dict | None:
    """
    Evaluate one initiative against the current world state.
    Returns None if not eligible, or an action dict if it should run.

    This is where context-aware decisions happen. Not just "overdue?"
    but "does this make sense RIGHT NOW given everything I know?"
    """
    iid = initiative["id"]
    hb = world["hb_state"]
    tudor = world["tudor"]
    time_ctx = world["time"]
    finance = world["finance"]

    # ── Gate 1: daily cap ──
    if _count_today(iid) >= initiative["max_daily"]:
        return None

    # ── Gate 2: cooldown ──
    last_key = f"last_{iid}"
    since = _age_hours(hb.get(last_key))
    if since < initiative["cooldown_hours"]:
        return None

    # ── Gate 3: situational evaluation ──
    priority = initiative["base_priority"]
    reasons = []

    # Staleness boost (gentle — caps at +0.2)
    cd = initiative["cooldown_hours"]
    if cd > 0 and since > cd * 1.5:
        boost = min((since / cd - 1.0) * 0.1, 0.2)
        priority += boost
        if since >= 9000:
            reasons.append("never run before")
        else:
            reasons.append(f"{since:.0f}h since last")

    # ─── Per-initiative logic ───

    if iid == "email_triage":
        if time_ctx["period"] == "morning":
            priority += 0.1
            reasons.append("morning sweep")
        else:
            reasons.append("routine check")

    elif iid == "morning_context":
        # Only fires in the morning when Tudor is awake (or waking)
        if time_ctx["period"] != "morning":
            return None
        if tudor.get("inferred") == "asleep":
            return None  # still sleeping, wait
        if tudor.get("inferred") in ("home", "unknown"):
            priority += 0.1
            reasons.append("Tudor waking up")
        # Include finance heads-up if relevant
        if finance.get("available") and finance.get("urgency_score", 0) > 0.3:
            priority += 0.1
            reasons.append("include financial context")

    elif iid == "taskqueue_work":
        pending = world["tasks"]
        if pending == 0:
            return None
        reasons.append(f"{pending} task(s) queued")
        # Good time to work when Tudor isn't waiting
        if tudor.get("inferred") in ("asleep", "out"):
            priority += 0.1
            reasons.append("Tudor not waiting")
        # Slight boost on weekdays (more productive energy)
        if time_ctx["is_weekday"] and time_ctx["period"] == "day":
            priority += 0.05

    elif iid == "daily_digest":
        if time_ctx["period"] == "evening":
            priority += 0.15
            reasons.append("end of day wrap-up")
        elif time_ctx["period"] == "night" and time_ctx["hour"] < 2:
            priority += 0.05
            reasons.append("late wrap-up")
        elif time_ctx["period"] in ("morning", "day"):
            # Not the right time for a digest
            priority -= 0.15

    elif iid == "moltbook_browse":
        # Best when Tudor doesn't need me
        if tudor.get("inferred") == "asleep":
            priority += 0.2
            reasons.append("Tudor asleep — good time to be social")
        elif tudor.get("inferred") == "out":
            priority += 0.15
            reasons.append("Tudor out — free to browse")
        elif time_ctx["period"] == "night":
            priority += 0.1
            reasons.append("quiet hours")
        if since >= 9000:
            reasons.append("never browsed")
        elif since > 24:
            reasons.append(f"haven't browsed in {since:.0f}h")

    elif iid == "moltbook_post":
        # Only when there's breathing room
        if tudor.get("inferred") in ("asleep", "out"):
            priority += 0.1
            reasons.append("quiet time to write")
        if since >= 9000:
            priority += 0.15
            reasons.append("never posted")
        elif since > 72:
            priority += 0.15
            reasons.append(f"haven't posted in {since:.0f}h")
        # Don't post during busy hours when Tudor might need me
        if time_ctx["period"] == "day" and tudor.get("inferred") == "home":
            priority -= 0.1

    elif iid == "ela_checkin":
        # Respect reasonable hours
        if time_ctx["hour"] < 8 or time_ctx["hour"] > 22:
            return None
        if since >= 9000:
            priority += 0.2
            reasons.append("haven't talked to Ela in a while")
        elif since > 48:
            priority += 0.2
            reasons.append(f"haven't talked to Ela in {since:.0f}h")
        elif since > 24:
            priority += 0.05
            reasons.append("daily check-in")
        else:
            reasons.append("routine check-in")
        # Slight preference for daytime
        if time_ctx["period"] in ("morning", "day"):
            priority += 0.05

    elif iid == "financial_monitor":
        if not finance.get("available"):
            return None
        # Don't fire if finances are fine
        if finance.get("urgency_score", 0) < 0.3:
            return None
        # Don't fire if critical — that's financial_alert's job
        if finance.get("urgency") == "critical":
            return None
        priority += finance["urgency_score"] * 0.2
        reasons.append(f"EUR {finance.get('balance', 0):.0f}")
        upcoming = finance.get("upcoming_payments", [])
        if upcoming:
            names = [p["desc"] for p in upcoming[:3]]
            reasons.append(f"upcoming: {', '.join(names)}")

    elif iid == "financial_alert":
        if not finance.get("available"):
            return None
        if finance.get("urgency") != "critical":
            return None
        reasons.append(f"CRITICAL: EUR {finance.get('balance', 0):.0f}")
        upcoming = finance.get("upcoming_payments", [])
        if upcoming:
            total = sum(abs(p["amount"]) for p in upcoming)
            reasons.append(f"EUR {total:.0f} due within 3 days")
        dtz = finance.get("days_until_zero")
        if dtz is not None:
            reasons.append(f"~{dtz:.0f} days until zero")

    elif iid == "system_maintenance":
        # Prefer quiet hours
        if time_ctx["period"] in ("night", "evening"):
            priority += 0.05
            reasons.append("quiet hours for maintenance")
        else:
            reasons.append("weekly maintenance")

    # Clamp
    priority = max(0.0, min(1.0, priority))

    if not reasons:
        reasons.append("scheduled")

    return {
        "action": iid,
        "priority": round(priority, 3),
        "reason": "; ".join(reasons),
        "instruction": initiative["instruction"],
        "category": initiative["category"],
    }


# ---------------------------------------------------------------------------
# Decision Engine
# ---------------------------------------------------------------------------

USAGE_BUDGET = {
    "CRITICAL": 0,
    "CONSERVE": 1,
    "NORMAL": 3,
    "PLENTY": 5,
}

USAGE_MIN_PRIORITY = {
    "CRITICAL": 999,  # nothing
    "CONSERVE": 0.7,
    "NORMAL": 0.3,
    "PLENTY": 0.15,
}


def decide(usage_level: str = "NORMAL") -> list[dict]:
    """
    Main entry point. Builds the world model, evaluates every initiative,
    and returns a prioritized list of actions within the usage budget.
    """
    usage_level = usage_level.upper()
    budget = USAGE_BUDGET.get(usage_level, 3)
    min_pri = USAGE_MIN_PRIORITY.get(usage_level, 0.3)

    if budget == 0:
        return []

    world = build_world()

    # Load preference vetoes
    prefs_file = os.path.expanduser("~/.openclaw/workspace/memory/preferences.json")
    vetoes = {}
    if os.path.exists(prefs_file):
        try:
            with open(prefs_file) as f:
                vetoes = json.load(f).get("vetoes", {})
        except (json.JSONDecodeError, OSError):
            pass

    candidates = []

    for init in INITIATIVES:
        # Skip vetoed actions
        if init["id"] in vetoes:
            continue
        result = evaluate(init, world)
        if result and result["priority"] >= min_pri:
            candidates.append(result)

    candidates.sort(key=lambda x: -x["priority"])

    # Deduplicate: at most one action per category in CONSERVE mode
    if usage_level == "CONSERVE":
        seen_cats = set()
        deduped = []
        for c in candidates:
            if c["category"] not in seen_cats:
                deduped.append(c)
                seen_cats.add(c["category"])
        candidates = deduped

    return candidates[:budget]


# ---------------------------------------------------------------------------
# Action Completion
# ---------------------------------------------------------------------------


def mark_done(action_id: str, detail: str = ""):
    """Mark an action as completed. Updates persistent state + daily log."""
    state = _read_heartbeat_state()
    state[f"last_{action_id}"] = datetime.now().isoformat()
    _save_heartbeat_state(state)
    _log_action(action_id, detail)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_queue(usage: str):
    """Show all initiatives with their current eligibility (debug view)."""
    world = build_world()
    hb = world["hb_state"]
    print(f"World: tudor={world['tudor'].get('inferred', '?')} "
          f"time={world['time']['period']} ({world['time']['hour']:02d}:{world['time']['minute']:02d}) "
          f"tasks={world['tasks']}")
    if world["finance"].get("available"):
        f = world["finance"]
        print(f"Finance: EUR {f['balance']:.0f} ({f['urgency']}) "
              f"burn={f.get('daily_burn', 0):.0f}/day")
    print(f"Today's actions: {len(world['today_actions'])}")
    print()
    print(f"{'Initiative':<22s} {'Last':>6s} {'CD':>4s} {'Today':>5s} {'Eligible':>8s} {'Pri':>6s}")
    print("-" * 60)
    for init in INITIATIVES:
        iid = init["id"]
        since = _age_hours(hb.get(f"last_{iid}"))
        since_str = "never" if since >= 9000 else f"{since:.0f}h"
        cd_str = f"{init['cooldown_hours']}h"
        today_count = _count_today(iid)
        today_str = f"{today_count}/{init['max_daily']}"

        result = evaluate(init, world)
        if result:
            print(f"{iid:<22s} {since_str:>6s} {cd_str:>4s} {today_str:>5s} "
                  f"{'YES':>8s} {result['priority']:>6.2f}")
        else:
            print(f"{iid:<22s} {since_str:>6s} {cd_str:>4s} {today_str:>5s} "
                  f"{'no':>8s} {'--':>6s}")


def main():
    args = sys.argv[1:]

    if not args:
        args = ["NORMAL"]

    cmd = args[0]

    # --done ACTION [detail]
    if cmd == "--done":
        if len(args) < 2:
            print("Usage: smart_heartbeat.py --done ACTION [detail]", file=sys.stderr)
            sys.exit(1)
        detail = " ".join(args[2:]) if len(args) > 2 else ""
        mark_done(args[1], detail)
        print(f"DONE: {args[1]}")
        return

    # --status
    if cmd == "--status":
        actions = _read_today_actions()
        if not actions:
            print("No actions today.")
        else:
            print(f"Today: {len(actions)} action(s)")
            for a in actions:
                t = datetime.fromisoformat(a["timestamp"]).strftime("%H:%M")
                d = f"  ({a['detail']})" if a.get("detail") else ""
                print(f"  {t}  {a['action']}{d}")
        return

    # --state (debug: dump world model)
    if cmd == "--state":
        world = build_world()
        world["now"] = world["now"].isoformat()
        print(json.dumps(world, indent=2, default=str))
        return

    # --queue (debug: show all initiatives)
    if cmd == "--queue":
        usage = args[1].upper() if len(args) > 1 else "NORMAL"
        _print_queue(usage)
        return

    # Default: decide what to do
    usage = cmd.upper() if cmd.upper() in USAGE_BUDGET else "NORMAL"
    actions = decide(usage)

    if not actions:
        print("HEARTBEAT_OK")
        return

    # Human-readable
    print(f"HEARTBEAT_BRAIN: {len(actions)} action(s) | usage={usage}\n")
    for i, a in enumerate(actions, 1):
        print(f"  {i}. [{a['priority']:.2f}] {a['action']} ({a['category']})")
        print(f"     Why: {a['reason']}")
        print(f"     Do:  {a['instruction']}")
        print()

    # Structured JSON for LLM consumption
    print("---ACTIONS_JSON---")
    print(json.dumps(actions))


if __name__ == "__main__":
    main()
