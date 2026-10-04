#!/usr/bin/env python3
"""Claude Code status line that also keeps ~/.claude/usage-limits.json fresh.

Claude Code hands the plan limits (5 hours, 7 days) only to the status line
command, so this is where the phone app gets them from. Sessions without plan
limits (API key, gateway) leave the file alone.

Install: copy to ~/.claude/ and point "statusLine" in ~/.claude/settings.json
at it: {"type": "command", "command": "python3 ~/.claude/claude-statusline.py"}
"""
import json
import os
import sys
import time

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

limits = data.get("rate_limits") or {}
windows = {k: limits.get(k) for k in ("five_hour", "seven_day") if limits.get(k)}
if windows:
    path = os.path.expanduser("~/.claude/usage-limits.json")
    try:
        with open(path + ".tmp", "w") as out:
            json.dump({**windows, "ts": time.time()}, out)
        os.replace(path + ".tmp", path)
    except OSError:
        pass

parts = [(data.get("model") or {}).get("display_name") or ""]
for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
    used = (windows.get(key) or {}).get("used_percentage")
    if used is not None:
        parts.append(f"{label} {round(used)}%")
print(" · ".join(p for p in parts if p))
