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
import urllib.request
from pathlib import Path

OPENCLAW_BIN = os.environ.get(
    "AGENT_BRIDGE_OPENCLAW_BIN",
    "/home/eliot/.npm-global/bin/openclaw"
)

# Where session history lives
SESSION_DIR = Path("/home/eliot/.openclaw/agents/main/sessions")

NUDGE_MESSAGES = [
    "You went silent. Run `python3 ~/projects/eliot-upgrades/smart_heartbeat.py $(python3 ~/projects/claude-usage-monitor/claude-usage.py --short 2>/dev/null | head -1)` and act on whatever it says. Don't stop until usage hits CONSERVE.",
]

# Network check settings
NETWORK_CHECK_URL = "https://api.anthropic.com/"
NETWORK_CHECK_TIMEOUT = 5
MAX_CONSECUTIVE_FAILURES = 5
BACKOFF_MULTIPLIER = 2
MAX_BACKOFF_SECONDS = 600  # 10 minutes


def check_network():
    """Quick connectivity check — any HTTP response means network is up."""
    try:
        req = urllib.request.Request(NETWORK_CHECK_URL, method="HEAD")
        urllib.request.urlopen(req, timeout=NETWORK_CHECK_TIMEOUT)
        return True
    except urllib.error.HTTPError:
        # Got an HTTP response (4xx/5xx) — network is fine, server just rejected
        return True
    except Exception:
        return False


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
    # Read last 100 lines for efficiency
    try:
        lines = session_file.read_text().strip().split("\n")[-100:]
        for line in lines:
            try:
                entry = json.loads(line)
                msg = entry.get("message", {})
                if msg.get("role") == "assistant":
                    ts_str = entry.get("timestamp", "")
                    if ts_str:
                        from datetime import datetime, timezone
                        # Parse ISO timestamp like 2026-03-21T21:16:36.225Z
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        last_ts = max(last_ts, dt.timestamp())
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    except Exception:
        pass

    return last_ts


def has_pending_actions():
    """Check if smart_heartbeat has any actions to recommend. Avoids waking
    the agent when there's genuinely nothing to do."""
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "smart_heartbeat.py"), "NORMAL"],
            capture_output=True, text=True, timeout=15,
        )
        return "HEARTBEAT_BRAIN" in result.stdout
    except Exception:
        # If we can't check, nudge anyway (fail-open)
        return True


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
    parser.add_argument("--timeout", type=int, default=600,
                        help="Seconds of silence before nudging")
    parser.add_argument("--once", action="store_true",
                        help="Send one nudge and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print without sending")
    args = parser.parse_args()

    nudge_idx = 0
    last_nudge_time = 0
    min_nudge_interval = args.timeout  # Don't nudge more often than the timeout
    consecutive_failures = 0
    current_poll = 30

    print(f"[SELF-NUDGE] Watching for {args.timeout}s of silence...")

    while True:
        # Network circuit breaker: don't attempt nudges if network is down
        if not check_network():
            consecutive_failures += 1
            if consecutive_failures <= 1:
                print("[SELF-NUDGE] Network unreachable, backing off...")
            backoff = min(
                current_poll * (BACKOFF_MULTIPLIER ** min(consecutive_failures, 8)),
                MAX_BACKOFF_SECONDS
            )
            time.sleep(backoff)
            continue

        # Network is back — reset backoff
        if consecutive_failures > 0:
            print(f"[SELF-NUDGE] Network restored after {consecutive_failures} failures")
            consecutive_failures = 0

        session_file = find_main_session_file()
        if not session_file:
            print("[SELF-NUDGE] No session file found, waiting...")
            time.sleep(30)
            continue

        # Check for last assistant message timestamp in the actual JSONL
        last_activity = last_assistant_activity(session_file)
        now = time.time()
        # If no assistant message found, use file mtime as fallback
        if last_activity == 0:
            last_activity = session_file.stat().st_mtime
        silence = now - last_activity

        if silence >= args.timeout and (now - last_nudge_time) >= min_nudge_interval:
            # Pre-check: only nudge if smart_heartbeat has actual actions
            if not has_pending_actions():
                # Nothing to do — don't waste tokens. Back off longer.
                last_nudge_time = now  # Reset timer so we don't check again immediately
                time.sleep(min_nudge_interval)
                continue

            msg = NUDGE_MESSAGES[nudge_idx % len(NUDGE_MESSAGES)]
            if send_nudge(msg, dry_run=args.dry_run):
                last_nudge_time = now
                nudge_idx += 1
                if args.once:
                    return
            else:
                # Nudge failed — back off to avoid hammering a dead gateway
                consecutive_failures += 1

        # Poll every 30 seconds
        time.sleep(30)


if __name__ == "__main__":
    main()
