"""Generate the iOS Shortcuts setup page HTML."""

import json

SHORTCUTS = [
    {
        "name": "Eliot: Left Home",
        "trigger": "When I leave [Home address]",
        "payload": {"type": "location", "data": {"event": "left", "location": "home"}},
        "color": "#ef4444",
    },
    {
        "name": "Eliot: Arrived Home",
        "trigger": "When I arrive at [Home address]",
        "payload": {"type": "location", "data": {"event": "arrived", "location": "home"}},
        "color": "#22c55e",
    },
    {
        "name": "Eliot: Sleep On",
        "trigger": "When Sleep Focus turns on",
        "payload": {"type": "focus", "data": {"mode": "sleep", "active": True}},
        "color": "#8b5cf6",
    },
    {
        "name": "Eliot: Sleep Off",
        "trigger": "When Sleep Focus turns off",
        "payload": {"type": "focus", "data": {"mode": "sleep", "active": False}},
        "color": "#a78bfa",
    },
    {
        "name": "Eliot: DND On",
        "trigger": "When Do Not Disturb turns on",
        "payload": {"type": "focus", "data": {"mode": "dnd", "active": True}},
        "color": "#f59e0b",
    },
    {
        "name": "Eliot: DND Off",
        "trigger": "When Do Not Disturb turns off",
        "payload": {"type": "focus", "data": {"mode": "dnd", "active": False}},
        "color": "#fbbf24",
    },
    {
        "name": "Eliot: Battery Low",
        "trigger": "When battery level equals 20%",
        "payload": {"type": "battery", "data": {"level": 20, "charging": False}},
        "color": "#f97316",
    },
    {
        "name": "Eliot: Charging",
        "trigger": "When iPhone connects to charger",
        "payload": {"type": "battery", "data": {"level": 0, "charging": True}},
        "note": "Level shows 0 (Shortcuts can't read exact level here). That's fine.",
        "color": "#06b6d4",
    },
]


def generate_setup_html(token: str) -> str:
    url = "http://100.116.147.22:18790/event"

    shortcut_cards = ""
    for i, s in enumerate(SHORTCUTS):
        payload_str = json.dumps(s["payload"], indent=2)
        # Compact version for the copy button (single line)
        payload_compact = json.dumps(s["payload"])
        note = f'<p class="note">{s["note"]}</p>' if s.get("note") else ""
        shortcut_cards += f"""
        <div class="card" style="border-left: 4px solid {s['color']}">
          <div class="card-name">{s['name']}</div>
          <div class="trigger">{s['trigger']}</div>
          {note}
          <pre id="payload-{i}">{payload_str}</pre>
          <button onclick="copyText('{payload_compact.replace(chr(39), chr(92)+chr(39))}', this)">Copy JSON</button>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Eliot - Shortcut Setup</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    max-width: 600px; margin: 0 auto; padding: 16px;
    background: #0a0a0a; color: #d4d4d4;
    -webkit-text-size-adjust: 100%;
  }}
  h1 {{ font-size: 1.4em; color: #fff; margin-bottom: 4px; }}
  h2 {{ font-size: 1.1em; color: #7eb8ff; margin: 28px 0 12px; }}
  p {{ line-height: 1.5; margin: 8px 0; }}
  code {{ background: #222; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; }}
  .subtitle {{ color: #6b7280; font-size: 0.9em; margin-bottom: 20px; }}

  .secret-box {{
    background: #1a1a1a; border: 1px solid #333; border-radius: 10px;
    padding: 14px; margin: 12px 0;
  }}
  .secret-box label {{ font-size: 0.8em; color: #6b7280; display: block; margin-bottom: 6px; }}
  .secret-val {{
    font-family: ui-monospace, monospace; font-size: 0.82em;
    word-break: break-all; color: #fbbf24; line-height: 1.4;
  }}

  .card {{
    background: #141414; border-radius: 10px; padding: 14px;
    margin: 10px 0; border-left: 4px solid #333;
  }}
  .card-name {{ font-weight: 600; color: #fff; font-size: 1em; }}
  .trigger {{ font-size: 0.85em; color: #9ca3af; margin: 4px 0 8px; }}
  .note {{ font-size: 0.8em; color: #f59e0b; margin: 4px 0; }}

  pre {{
    background: #1e1e1e; padding: 10px; border-radius: 8px;
    font-size: 0.8em; overflow-x: auto; color: #a5f3fc;
    line-height: 1.4; white-space: pre-wrap;
  }}

  button {{
    background: #2563eb; color: #fff; border: none;
    padding: 11px 16px; border-radius: 8px; font-size: 0.9em;
    cursor: pointer; width: 100%; margin-top: 8px;
    -webkit-tap-highlight-color: transparent;
    transition: background 0.15s;
  }}
  button:active {{ background: #1d4ed8; }}
  button.copied {{ background: #16a34a; }}

  .steps {{ margin: 12px 0; padding-left: 1.4em; }}
  .steps li {{
    margin: 10px 0; padding-left: 4px; line-height: 1.5; color: #d4d4d4;
  }}
  .steps li::marker {{ color: #7eb8ff; font-weight: bold; }}

  .divider {{ border: none; border-top: 1px solid #222; margin: 24px 0; }}

  .manual-section {{
    background: #0f172a; border: 1px solid #1e3a5f;
    border-radius: 10px; padding: 14px; margin: 12px 0;
  }}

  .test-section {{
    background: #0a1a0a; border: 1px solid #1a3a1a;
    border-radius: 10px; padding: 14px; margin: 16px 0;
  }}
  #test-result {{
    font-family: ui-monospace, monospace; font-size: 0.82em;
    margin-top: 8px; min-height: 20px;
  }}
</style>
</head>
<body>

<h1>Eliot Webhook Setup</h1>
<p class="subtitle">iPhone Shortcuts &rarr; Eliot's context system</p>

<div class="secret-box">
  <label>Webhook URL</label>
  <div class="secret-val">{url}</div>
  <button onclick="copyText('{url}', this)">Copy URL</button>
</div>

<div class="secret-box">
  <label>Authorization Header</label>
  <div class="secret-val">Bearer {token}</div>
  <button onclick="copyText('Bearer {token}', this)">Copy Full Token</button>
</div>

<hr class="divider">

<h2>Setup (one time per automation)</h2>

<ol class="steps">
  <li>Open <b>Shortcuts</b> &rarr; <b>Automation</b> tab</li>
  <li>Tap <b>+</b> &rarr; pick the trigger listed on the card</li>
  <li>Set to <b>Run Immediately</b></li>
  <li>Add action: <b>Get Contents of URL</b></li>
  <li>Paste the webhook URL</li>
  <li>Method: <b>POST</b></li>
  <li>Add header: <code>Authorization</code> = paste the token above</li>
  <li>Add header: <code>Content-Type</code> = <code>application/json</code></li>
  <li>Request Body &rarr; <b>File</b> &rarr; tap &rarr; <b>Replace with Text</b></li>
  <li>Paste the JSON from the card below</li>
</ol>

<hr class="divider">

<h2>Automations</h2>
{shortcut_cards}

<hr class="divider">

<h2>Siri Trigger: "Tell Eliot"</h2>

<div class="manual-section">
  <p style="font-size: 0.85em; margin-bottom: 10px;">
    This is a <b>Shortcut</b> (not Automation). Create it in the Shortcuts tab.
  </p>
  <ol class="steps">
    <li>Shortcuts tab &rarr; <b>+</b> &rarr; name it <b>Tell Eliot</b></li>
    <li>Add: <b>Ask for Input</b> (Text, prompt: "Message for Eliot")</li>
    <li>Add: <b>Text</b> action, type:<br>
      <pre>{{"type":"manual","data":{{"message":"<i>tap here, insert Provided Input variable</i>"}}}}</pre></li>
    <li>Add: <b>Get Contents of URL</b><br>
      URL, method POST, same headers as above</li>
    <li>Body &rarr; File &rarr; select the Text from step 3</li>
  </ol>
  <p style="font-size: 0.85em; color: #7eb8ff; margin-top: 8px;">
    "Hey Siri, Tell Eliot" &rarr; speaks your message &rarr; Eliot receives it.
  </p>
</div>

<hr class="divider">

<h2>Test</h2>

<div class="test-section">
  <button onclick="testConnection()" id="test-btn">Test Connection</button>
  <div id="test-result"></div>

  <button onclick="testEvent()" id="test-event-btn" style="margin-top: 8px; background: #4b5563;">
    Send Test Event
  </button>
  <div id="test-event-result" style="font-family: ui-monospace, monospace; font-size: 0.82em; margin-top: 8px;"></div>
</div>

<p style="color: #4b5563; font-size: 0.75em; margin-top: 24px; text-align: center;">
  Tailscale only. Token not exposed to internet.
</p>

<script>
function copyText(text, btn) {{
  const orig = btn.dataset.orig || btn.textContent;
  btn.dataset.orig = orig;

  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(() => flash(btn, orig)).catch(() => fallback(text, btn, orig));
  }} else {{
    fallback(text, btn, orig);
  }}
}}

function fallback(text, btn, orig) {{
  var ta = document.createElement('textarea');
  ta.value = text; ta.style.cssText = 'position:fixed;left:-9999px';
  document.body.appendChild(ta); ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  flash(btn, orig);
}}

function flash(btn, orig) {{
  btn.classList.add('copied'); btn.textContent = 'Copied!';
  setTimeout(function() {{ btn.classList.remove('copied'); btn.textContent = orig; }}, 1500);
}}

function testConnection() {{
  var btn = document.getElementById('test-btn');
  var res = document.getElementById('test-result');
  btn.textContent = 'Testing...'; btn.disabled = true; res.textContent = '';

  fetch('/health').then(function(r) {{ return r.json(); }}).then(function(data) {{
    res.style.color = '#86efac';
    res.textContent = 'OK - ' + data.events_total + ' events recorded';
    btn.textContent = 'Test Connection'; btn.disabled = false;
  }}).catch(function(err) {{
    res.style.color = '#fca5a5';
    res.textContent = 'Failed: ' + err.message;
    btn.textContent = 'Test Connection'; btn.disabled = false;
  }});
}}

function testEvent() {{
  var btn = document.getElementById('test-event-btn');
  var res = document.getElementById('test-event-result');
  btn.textContent = 'Sending...'; btn.disabled = true; res.textContent = '';

  fetch('/event', {{
    method: 'POST',
    headers: {{
      'Authorization': 'Bearer {token}',
      'Content-Type': 'application/json'
    }},
    body: JSON.stringify({{type: 'manual', data: {{message: 'test from setup page'}}}})
  }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
    if (data.status === 'received') {{
      res.style.color = '#86efac';
      res.textContent = 'Event sent and received!';
    }} else {{
      res.style.color = '#fca5a5';
      res.textContent = 'Error: ' + JSON.stringify(data);
    }}
    btn.textContent = 'Send Test Event'; btn.disabled = false;
  }}).catch(function(err) {{
    res.style.color = '#fca5a5';
    res.textContent = 'Failed: ' + err.message;
    btn.textContent = 'Send Test Event'; btn.disabled = false;
  }});
}}
</script>
</body></html>"""
