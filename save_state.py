#!/usr/bin/env python3
"""
Write ~/workspace/CONTINUATION.md before gateway restarts or session ends.

Usage:
  save_state.py "what I was doing" "what to pick up next"
  save_state.py --auto   # reads from stdin or generates from context

The file is designed to be read cold — by a future Eliot who has no session memory.
"""

import json
import os
import sys
from datetime import datetime

CONTINUATION_FILE = os.path.expanduser("~/workspace/CONTINUATION.md")
STATE_FILE = "/home/eliot/workspace/data/tudor-state.json"
TASKQUEUE_FILE = os.path.expanduser("~/workspace/TASKQUEUE.md")


def read_taskqueue():
    if not os.path.exists(TASKQUEUE_FILE):
        return []
    tasks = []
    with open(TASKQUEUE_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("- [ ]"):
                tasks.append(line[6:].strip())
            elif line.startswith("- [x]"):
                tasks.append("[done] " + line[6:].strip())
    return tasks


def read_tudor_state():
    if not os.path.exists(STATE_FILE):
        return "No state file."
    with open(STATE_FILE) as f:
        state = json.load(f)
    parts = []
    for key, val in state.items():
        if isinstance(val, dict):
            summary = ", ".join(f"{k}={v}" for k, v in val.items() if k != "updated_at")
            parts.append(f"{key}: {summary}")
    return "; ".join(parts) if parts else "Empty state."


def save(what_happened: str, pick_up_next: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tasks = read_taskqueue()
    tudor_state = read_tudor_state()

    tasks_block = ""
    if tasks:
        tasks_block = "\n".join(f"- {t}" for t in tasks)
    else:
        tasks_block = "No queued tasks."

    content = f"""# CONTINUATION.md
Written: {now}

## What Was Happening
{what_happened}

## Tudor's State
{tudor_state}

## Task Queue
{tasks_block}

## Pick Up Next
{pick_up_next}

## Notes
Read MEMORY.md and TASKQUEUE.md for full context. This file is a snapshot, not the source of truth.
"""

    with open(CONTINUATION_FILE, "w") as f:
        f.write(content)
    print(f"Saved to {CONTINUATION_FILE}")


def main():
    if len(sys.argv) >= 3:
        save(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "--auto":
        # Read from environment or generate minimal
        what = os.environ.get("ELIOT_CONTEXT", "Session ended normally. Check TASKQUEUE.md.")
        pick_up = os.environ.get("ELIOT_NEXT", "Check heartbeat, then TASKQUEUE.md for pending work.")
        save(what, pick_up)
    else:
        print('Usage: save_state.py "what happened" "what to pick up"')
        print('       save_state.py --auto')
        sys.exit(1)


if __name__ == "__main__":
    main()
