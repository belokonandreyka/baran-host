#!/usr/bin/env python3
"""Claude Code status line that also keeps ~/.claude/usage-limits.json fresh.

Claude Code hands the plan limits (5 hours, 7 days) only to the status line
command, so this is where the phone app gets them from. Sessions without plan
limits (API key, gateway) leave the file alone.

Install: copy to ~/.claude/ and point "statusLine" in ~/.claude/settings.json
at it: {"type": "command", "command": "python3 ~/.claude/claude-statusline.py"}
"""
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

SCOPED = os.path.expanduser("~/.claude/usage-scoped.json")
REFRESH_EVERY = 300
PLAN_WINDOWS = {"session": "five_hour", "weekly_all": "seven_day"}


def save(path, value):
    try:
        with open(path + ".tmp", "w") as out:
            json.dump(value, out)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def token():
    """Claude Code's login: the Keychain on macOS, a file elsewhere."""
    try:
        raw = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                             capture_output=True, text=True, timeout=10).stdout
        if not raw.strip():
            raw = open(os.path.expanduser("~/.claude/.credentials.json")).read()
        return json.loads(raw)["claudeAiOauth"]["accessToken"]
    except Exception:
        return None


def refresh():
    """Fetches the per-model weekly limits. Returns what it stored, or None."""
    access = token()
    if not access:
        return None
    request = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
        "Authorization": "Bearer " + access, "anthropic-beta": "oauth-2025-04-20"})
    with urllib.request.urlopen(request, timeout=15) as response:
        usage = json.load(response)
    stored = {"scoped": [], "ts": time.time()}
    for limit in usage.get("limits") or []:
        if limit.get("percent") is None:
            continue
        resets = limit.get("resets_at")
        window = {"used_percentage": limit["percent"],
                  "resets_at": datetime.datetime.fromisoformat(resets).timestamp() if resets else None}
        name = ((limit.get("scope") or {}).get("model") or {}).get("display_name")
        if limit.get("kind") == "weekly_scoped" and name:
            stored["scoped"].append({"name": name, **window})
        # Claude Code leaves a window out of the status line hand-off at times.
        elif limit.get("kind") in PLAN_WINDOWS:
            stored[PLAN_WINDOWS[limit["kind"]]] = window
    save(SCOPED, stored)
    return stored


if sys.argv[1:2] == ["--refresh"]:
    try:
        print(json.dumps(refresh()))
    except Exception as error:
        print(f"refresh failed: {error}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

limits = data.get("rate_limits") or {}
windows = {k: limits.get(k) for k in ("five_hour", "seven_day") if limits.get(k)}
if windows:
    save(os.path.expanduser("~/.claude/usage-limits.json"), {**windows, "ts": time.time()})
    try:
        stale = time.time() - os.path.getmtime(SCOPED) > REFRESH_EVERY
    except OSError:
        stale = True
    if stale:
        # Touch first, so that a failing refresh is not retried on every redraw.
        try:
            os.utime(SCOPED) if os.path.exists(SCOPED) else save(SCOPED, {"scoped": [], "ts": 0})
            subprocess.Popen([sys.executable, os.path.realpath(__file__), "--refresh"], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

parts = [(data.get("model") or {}).get("display_name") or ""]
for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
    used = (windows.get(key) or {}).get("used_percentage")
    if used is not None:
        parts.append(f"{label} {round(used)}%")
print(" · ".join(p for p in parts if p))
