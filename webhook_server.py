#!/usr/bin/env python3
"""
Eliot's webhook server. Receives events from Tudor's iPhone via iOS Shortcuts.

Listens on port 18790 (Tailscale-only).
Auth: Bearer token from ~/.openclaw/.secrets/webhook-token.txt

Endpoints:
  GET  /health  - monitoring (no auth)
  GET  /setup   - iOS Shortcuts setup guide (Tailscale-only, no auth)
  POST /event   - receive events (auth required)
"""

import json
import os
import sys
import logging
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Add project dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn, init_db
from reactions import react
from setup_page import generate_setup_html

HOST = "0.0.0.0"
PORT = int(os.environ.get("ELIOT_WEBHOOK_PORT", 18790))
TOKEN_FILE = os.environ.get(
    "ELIOT_TOKEN_FILE", "/home/eliot/.openclaw/.secrets/webhook-token.txt"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("eliot-webhook")


def load_token() -> str:
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        log.error("Token file not found: %s", TOKEN_FILE)
        log.error("Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\" > %s", TOKEN_FILE)
        sys.exit(1)


TOKEN = None  # loaded at startup


class WebhookServer(HTTPServer):
    allow_reuse_address = True


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log.info("%s %s", self.address_string(), format % args)

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {TOKEN}":
            return True
        self._send_json(401, {"error": "unauthorized"})
        log.warning("Unauthorized request from %s", self.address_string())
        return False

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            conn = get_conn()
            event_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            last_event = conn.execute(
                "SELECT timestamp, event_type FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            self._send_json(200, {
                "status": "ok",
                "uptime_check": datetime.now().isoformat(),
                "events_total": event_count,
                "last_event": {
                    "timestamp": last_event["timestamp"],
                    "type": last_event["event_type"],
                } if last_event else None,
            })
        elif self.path == "/setup":
            self._send_html(generate_setup_html(TOKEN))
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/event":
            self._send_json(404, {"error": "not found"})
            return

        if not self._check_auth():
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "empty body"})
            return

        if content_length > 65536:
            self._send_json(413, {"error": "payload too large"})
            return

        try:
            body = self.rfile.read(content_length)
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json(400, {"error": f"invalid json: {e}"})
            return

        event_type = payload.get("type")
        if not event_type:
            self._send_json(400, {"error": "missing 'type' field"})
            return

        data = payload.get("data", {})
        timestamp = payload.get("timestamp", datetime.now().isoformat())
        source = payload.get("source", "iphone")

        # Store in database
        conn = get_conn()
        conn.execute(
            "INSERT INTO events (timestamp, event_type, payload, source) VALUES (?, ?, ?, ?)",
            (timestamp, event_type, json.dumps(data), source),
        )
        conn.commit()
        conn.close()

        # Fire reactions
        reaction_result = react(event_type, data)

        log.info("Event: type=%s source=%s reaction=%s", event_type, source, reaction_result.get("action"))

        self._send_json(200, {
            "status": "received",
            "event_type": event_type,
            "reaction": reaction_result,
        })


def main():
    global TOKEN
    init_db()
    TOKEN = load_token()
    log.info("Token loaded from %s", TOKEN_FILE)

    server = WebhookServer((HOST, PORT), WebhookHandler)
    log.info("Eliot webhook server listening on %s:%d", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
