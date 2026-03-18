#!/usr/bin/env python3
"""
Self-nudge daemon: monitors session activity and sends a wake-up message
if no output is detected for TIMEOUT_SECONDS.

Watches the gateway session JSONL for new assistant messages.
If the assistant hasn't produced output in TIMEOUT_SECONDS, sends
a nudge via `openclaw gateway call chat.send`.

Usage:
    python3 self-nudge.py [--timeout 120] [--once] [--dry-run]

Options:
    --timeout N     Seconds of silence before nudging (default: 120)
    --once          Send one nudge and exit (instead of looping)
    --dry-run       Print what would be sent without sending
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OPENCLAW_BIN = os.environ.get(
    "AGENT_BRIDGE_OPENCLAW_BIN",
    "/home/eliot/.npm-global/bin/openclaw"
)

# Where session history lives
SESSION_DIR = Path("/home/eliot/.openclaw/sessions")

NUDGE_MESSAGES = [
    "You went silent. Run `python3 ~/projects/eliot-upgrades/smart_heartbeat.py $(python3 ~/projects/claude-usage-monitor/claude-usage.py --short 2>/dev/null | head -1)` and act on whatever it says. Don't stop until usage hits CONSERVE.",
]


def find_main_session_file():
    """Find the most recent main session JSONL file."""
    candidates = sorted(
        SESSION_DIR.glob("agent__main__main*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    # Fallback: any recent session file
    all_sessions = sorted(
        SESSION_DIR.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return all_sessions[0] if all_sessions else None


def last_assistant_activity(session_file):
    """Get the timestamp of the last assistant message in the session."""
    if not session_file or not session_file.exists():
        return 0

    last_ts = 0
    # Read last 50 lines for efficiency
    try:
        lines = session_file.read_text().strip().split("\n")[-50:]
        for line in lines:
            try:
                entry = json.loads(line)
                if entry.get("role") == "assistant":
                    # Use file mtime as proxy if no timestamp in entry
                    last_ts = max(last_ts, entry.get("ts", 0))
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception:
        pass

    # If no timestamp found in entries, use file mtime
    if last_ts == 0 and session_file.exists():
        last_ts = session_file.stat().st_mtime

    return last_ts


def send_nudge(message, dry_run=False):
    """Send a nudge message via openclaw gateway call chat.send."""
    import uuid
    key = f"nudge-{uuid.uuid4().hex[:12]}"
    params = json.dumps({
        "message": f"[Self-Nudge] {message}",
        "idempotencyKey": key,
        "sessionKey": "main",
    })

    if dry_run:
        print(f"[DRY RUN] Would send: {message}")
        return True

    try:
        result = subprocess.run(
            [OPENCLAW_BIN, "gateway", "call", "chat.send",
             "--params", params, "--json", "--timeout", "10000"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            print(f"[NUDGE SENT] {message}")
            return True
        else:
            print(f"[NUDGE FAILED] {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"[NUDGE ERROR] {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Self-nudge daemon")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Seconds of silence before nudging")
    parser.add_argument("--once", action="store_true",
                        help="Send one nudge and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print without sending")
    args = parser.parse_args()

    nudge_idx = 0
    last_nudge_time = 0
    min_nudge_interval = args.timeout  # Don't nudge more often than the timeout

    print(f"[SELF-NUDGE] Watching for {args.timeout}s of silence...")

    while True:
        session_file = find_main_session_file()
        if not session_file:
            print("[SELF-NUDGE] No session file found, waiting...")
            time.sleep(30)
            continue

        # Check file mtime as proxy for activity
        last_activity = session_file.stat().st_mtime
        now = time.time()
        silence = now - last_activity

        if silence >= args.timeout and (now - last_nudge_time) >= min_nudge_interval:
            msg = NUDGE_MESSAGES[nudge_idx % len(NUDGE_MESSAGES)]
            if send_nudge(msg, dry_run=args.dry_run):
                last_nudge_time = now
                nudge_idx += 1
                if args.once:
                    return

        # Poll every 30 seconds
        time.sleep(30)


if __name__ == "__main__":
    main()
