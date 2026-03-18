#!/usr/bin/env python3
"""
Heartbeat decision engine. Replaces the checklist with a brain.

Run this at the start of each heartbeat. It outputs a prioritized list
of ACTIONS to take, not things to check. The LLM heartbeat executes them.

State is tracked in heartbeat-state.json so the brain knows what's stale.
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn, init_db

STATE_FILE = os.path.expanduser("~/.openclaw/workspace/memory/heartbeat-state.json")
TASKQUEUE = os.path.expanduser("~/.openclaw/workspace/TASKQUEUE.md")
PREFERENCES_FILE = os.path.expanduser("~/.openclaw/workspace/memory/preferences.json")

# Preference vetoes: action name -> reason why it's blocked
# Loaded from preferences.json, editable by the agent
def load_preferences() -> dict:
    """Load action vetoes/preferences. Format: {"vetoes": {"action_name": "reason"}}"""
    if os.path.exists(PREFERENCES_FILE):
        with open(PREFERENCES_FILE) as f:
            return json.load(f)
    return {"vetoes": {}}


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def hours_since(iso_str: str | None) -> float:
    if not iso_str:
        return 9999
    try:
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now() - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return 9999


def count_pending_tasks() -> int:
    if not os.path.exists(TASKQUEUE):
        return 0
    count = 0
    with open(TASKQUEUE) as f:
        for line in f:
            if line.strip().startswith("- [ ]"):
                count += 1
    return count


def get_financial_urgency() -> tuple[float, str]:
    """Return (urgency 0-1, reason)."""
    try:
        init_db()
        conn = get_conn()
        row = conn.execute(
            """SELECT balance FROM transactions
               WHERE currency='EUR' AND product='Current' AND balance IS NOT NULL
               AND state='COMPLETED' ORDER BY completed_date DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        if row:
            bal = row["balance"]
            if bal < 50:
                return (1.0, f"Balance critical: EUR {bal:.0f}")
            if bal < 150:
                return (0.7, f"Balance low: EUR {bal:.0f}")
            if bal < 300:
                return (0.3, f"Balance moderate: EUR {bal:.0f}")
        return (0.0, "")
    except Exception:
        return (0.0, "")


def score_actions(state: dict, usage_level: str) -> list[dict]:
    """Score potential proactive actions. Returns sorted list."""
    now = datetime.now()
    actions = []

    # --- Relationship: Ela ---
    h = hours_since(state.get("last_ela_contact"))
    if h > 48:
        actions.append({
            "action": "ela_checkin",
            "priority": min(0.6 + (h - 48) / 72, 0.9),  # grows over time
            "reason": f"Haven't talked to Ela in {h:.0f}h",
            "instruction": "Check in with Ela via agent-send. Ask how things are, how Mika is doing. Keep it natural, not forced.",
        })

    # --- Community: Moltbook ---
    h = hours_since(state.get("last_moltbook_browse"))
    if h > 18:
        actions.append({
            "action": "moltbook_browse",
            "priority": min(0.5 + (h - 18) / 48, 0.8),
            "reason": f"Haven't browsed Moltbook in {h:.0f}h",
            "instruction": "Browse Moltbook recent posts. Read what other agents are building. Comment on anything genuinely interesting. Don't force engagement.",
        })

    h = hours_since(state.get("last_moltbook_post"))
    if h > 72:
        actions.append({
            "action": "moltbook_post",
            "priority": 0.4,
            "reason": f"Haven't posted to Moltbook in {h:.0f}h",
            "instruction": "Post something to Moltbook — a build update, an observation, a question. Only if you have something worth saying.",
        })

    # --- Finance ---
    fin_urgency, fin_reason = get_financial_urgency()
    if fin_urgency > 0.3:
        actions.append({
            "action": "financial_check",
            "priority": fin_urgency,
            "reason": fin_reason,
            "instruction": "Run eliot-ctx forecast. If Tudor needs to know something urgent, tell him naturally (not a data dump). If it's just low but not critical, log it and move on.",
        })

    # --- Task queue ---
    pending = count_pending_tasks()
    if pending > 0:
        actions.append({
            "action": "taskqueue_work",
            "priority": 0.5,
            "reason": f"{pending} tasks queued",
            "instruction": f"Pick the highest-value task from TASKQUEUE.md and work on it. Mark it done when finished.",
        })

    # --- Self-maintenance ---
    h = hours_since(state.get("last_digest"))
    if h > 20:
        actions.append({
            "action": "daily_digest",
            "priority": 0.3,
            "reason": f"No digest in {h:.0f}h",
            "instruction": "Run eliot-ctx digest to capture today's activity.",
        })

    # --- Filter by preferences/vetoes ---
    prefs = load_preferences()
    vetoes = prefs.get("vetoes", {})
    actions = [a for a in actions if a["action"] not in vetoes]

    # --- Scale by usage ---
    if usage_level == "CRITICAL":
        return []
    if usage_level == "CONSERVE":
        actions = [a for a in actions if a["priority"] >= 0.8]
        max_actions = 1
    elif usage_level == "NORMAL":
        max_actions = 2
    else:  # PLENTY
        max_actions = 3

    actions.sort(key=lambda x: -x["priority"])
    return actions[:max_actions]


def mark_done(action_name: str):
    """Call after completing an action to update state."""
    state = load_state()
    key_map = {
        "ela_checkin": "last_ela_contact",
        "moltbook_browse": "last_moltbook_browse",
        "moltbook_post": "last_moltbook_post",
        "financial_check": "last_financial_check",
        "taskqueue_work": "last_taskqueue_work",
        "daily_digest": "last_digest",
    }
    key = key_map.get(action_name, f"last_{action_name}")
    state[key] = datetime.now().isoformat()
    save_state(state)


def main():
    # Parse usage level from args or default
    usage = "NORMAL"
    if len(sys.argv) > 1:
        usage = sys.argv[1].upper()

    # Special case: mark an action as done
    if len(sys.argv) > 2 and sys.argv[1] == "--done":
        mark_done(sys.argv[2])
        print(f"Marked {sys.argv[2]} as done.")
        return

    state = load_state()
    actions = score_actions(state, usage)

    if not actions:
        print("HEARTBEAT_BRAIN: No proactive actions needed. Usage: " + usage)
        return

    print(f"HEARTBEAT_BRAIN: {len(actions)} action(s) at usage level {usage}\n")
    for i, a in enumerate(actions, 1):
        print(f"  {i}. [{a['priority']:.1f}] {a['action']}")
        print(f"     Why: {a['reason']}")
        print(f"     Do:  {a['instruction']}")
        print()

    # Also output as structured data for LLM parsing
    print("---ACTIONS_JSON---")
    print(json.dumps([{
        "action": a["action"],
        "instruction": a["instruction"],
    } for a in actions]))


if __name__ == "__main__":
    main()
