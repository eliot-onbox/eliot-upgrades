"""Event reaction handlers. Called by the webhook server when events arrive."""

import json
import os
from datetime import datetime

STATE_FILE = os.environ.get(
    "TUDOR_STATE_FILE", "/home/eliot/.openclaw/workspace/data/tudor-state.json"
)


def _read_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def _write_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def handle_location(data: dict):
    """Tudor's location changed. Update state file for heartbeat to read."""
    state = _read_state()
    state["location"] = {
        "name": data.get("location", "unknown"),
        "event": data.get("event", "unknown"),  # arrived, left
        "updated_at": datetime.now().isoformat(),
    }
    _write_state(state)
    return {"action": "state_updated", "location": state["location"]}


def handle_battery(data: dict):
    """Battery level reported. Just update state, no nagging."""
    state = _read_state()
    state["battery"] = {
        "level": data.get("level"),
        "charging": data.get("charging", False),
        "updated_at": datetime.now().isoformat(),
    }
    _write_state(state)
    return {"action": "state_updated", "battery": state["battery"]}


def handle_focus(data: dict):
    """Focus mode changed (sleep, DND, etc)."""
    state = _read_state()
    state["focus"] = {
        "mode": data.get("mode", "unknown"),
        "active": data.get("active", True),
        "updated_at": datetime.now().isoformat(),
    }
    _write_state(state)
    return {"action": "state_updated", "focus": state["focus"]}


def handle_manual(data: dict):
    """Manual trigger from Tudor via Siri or Shortcut button."""
    state = _read_state()
    state["last_manual"] = {
        "message": data.get("message", ""),
        "updated_at": datetime.now().isoformat(),
    }
    _write_state(state)
    return {"action": "state_updated", "message": data.get("message", "")}


# Dispatch table
HANDLERS = {
    "location": handle_location,
    "battery": handle_battery,
    "focus": handle_focus,
    "manual": handle_manual,
}


def react(event_type: str, data: dict) -> dict:
    handler = HANDLERS.get(event_type)
    if handler:
        return handler(data)
    return {"action": "logged_only", "reason": f"no handler for {event_type}"}
