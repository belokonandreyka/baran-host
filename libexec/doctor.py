"""What works on this host for the Baran app, and the hooks it can set up.

  baran doctor [--json]              checks, versions and integrations
  baran integrate claude|codex|pi           install or update one integration
  baran integrate claude|codex|pi --remove  take it out again

The app runs these over SSH; --json is what it reads.
"""
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BASE = os.path.expanduser("~/.config/baran")
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
CODEX_HOOKS = os.path.expanduser("~/.codex/hooks.json")
CODEX_CONFIG = os.path.expanduser("~/.codex/config.toml")
CODEX_EVENTS = ("Stop", "PermissionRequest")
# Stop: the reply. The others: Claude waits for you (a permission, a
# question, a plan to approve).
CLAUDE_EVENTS = (("Stop", None), ("PermissionRequest", None), ("PreToolUse", "AskUserQuestion|ExitPlanMode"))
PI_EXTENSIONS = os.path.expanduser("~/.pi/agent/extensions")
BUNDLED_PI = os.path.join(ROOT, "extensions", "baran-push.ts")
LATEST = "https://baran.party/latest"


def version():
    source = open(os.path.join(ROOT, "bin", "baran"), encoding="utf-8").read()
    return re.search(r'VERSION = "([^"]+)"', source).group(1)


def latest():
    """The version on the main branch; None when offline."""
    try:
        with urllib.request.urlopen(LATEST, timeout=4) as response:
            found = re.search(r'VERSION = "([^"]+)"', response.read().decode("utf-8", "replace"))
            return found.group(1) if found else None
    except Exception:
        return None


def newer_than(a, b):
    parts = lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")]
    return parts(a) > parts(b)


def command_path():
    """How hooks should call baran: the link the user runs, not the file behind it."""
    return os.environ.get("BARAN_BIN") or shutil.which("baran") or os.path.join(ROOT, "bin", "baran")


def install_kind():
    if "/Cellar/" in ROOT or "/homebrew/" in ROOT or "/linuxbrew/" in ROOT:
        return "brew"
    if ROOT.startswith(os.path.realpath(os.path.expanduser("~/.local/share")) + "/"):
        return "script"
    return "other"


def update_command():
    return {
        "brew": "brew update && brew upgrade belokonandreyka/baran/baran",
        "script": "curl -fsSL https://baran.party/install.sh | sh",
    }.get(install_kind())


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


# Checks

def checks():
    found = []

    def check(key, title, ok, detail):
        found.append({"id": key, "title": title, "ok": bool(ok), "detail": detail})

    apns = read_json(os.path.join(BASE, "apns.json")) or {}
    key_file = os.path.expanduser(apns.get("key_path", "")) if apns else ""
    check("apns", "Ключ сповіщень", key_file and os.path.exists(key_file),
          "~/.config/baran/apns.json і ключ .p8 на місці" if key_file and os.path.exists(key_file)
          else "Немає ~/.config/baran/apns.json або ключа .p8: пуші не підуть")

    devices = read_json(os.path.join(BASE, "devices.json")) or []
    check("devices", "Телефон", devices,
          f"Зареєстровано пристроїв: {len(devices)}" if devices
          else "Жоден телефон не зареєстрований: увімкніть сповіщення в застосунку")

    tools = [name for name in ("python3", "openssl", "curl") if not shutil.which(name)]
    http2 = False
    if shutil.which("curl"):
        http2 = "HTTP2" in subprocess.run(["curl", "--version"], capture_output=True, text=True).stdout
    check("tools", "Інструменти для пушів", not tools and http2,
          "python3, openssl і curl з HTTP/2" if not tools and http2
          else "Бракує: " + ", ".join(tools + ([] if http2 else ["curl з HTTP/2"])))

    herdr = shutil.which("herdr") or next((p for p in (os.path.expanduser("~/.local/bin/herdr"), "/opt/homebrew/bin/herdr")
                                          if os.path.exists(p)), None)
    check("herdr", "herdr", herdr, "Сесії, сайдбар і чат" if herdr else "Не встановлено: лише звичайний термінал")

    sftp = False
    try:
        sftp = any(re.match(r"\s*Subsystem\s+sftp\s", line, re.I) for line in open("/etc/ssh/sshd_config"))
        for name in os.listdir("/etc/ssh/sshd_config.d") if os.path.isdir("/etc/ssh/sshd_config.d") else []:
            sftp = sftp or any(re.match(r"\s*Subsystem\s+sftp\s", line, re.I)
                               for line in open(os.path.join("/etc/ssh/sshd_config.d", name), errors="replace"))
    except OSError:
        pass
    check("sftp", "Завантаження файлів", sftp, "SFTP увімкнений" if sftp else "SFTP не знайдено в sshd_config")
    return found


# Integrations

def claude_state():
    present = bool(shutil.which("claude")) or os.path.isdir(os.path.expanduser("~/.claude"))
    settings = read_json(CLAUDE_SETTINGS) or {}
    path = command_path()
    hooks = settings.get("hooks") or {}

    def commands(event):
        return [h.get("command", "") for entry in hooks.get(event) or [] for h in entry.get("hooks") or []]

    ours = [c for event in hooks for c in commands(event) if "baran push claude-hook" in c]
    line = (settings.get("statusLine") or {}).get("command", "")
    placed = sorted(event for event in hooks if any("baran push claude-hook" in c for c in commands(event)))
    hooks_current = placed == sorted(e for e, _ in CLAUDE_EVENTS) and len(ours) == len(CLAUDE_EVENTS) \
        and all(c == f"{path} push claude-hook" for c in ours)
    if not ours and "baran statusline" not in line:
        state = "missing"
    elif hooks_current and line == f"{path} statusline":
        state = "installed"
    elif hooks_current and "baran statusline" not in line:
        # Pushes work; another status line is kept, so limits do not refresh.
        state = "partial"
    else:
        state = "outdated"
    return {"id": "claude", "name": "Claude Code", "present": present, "state": state}


def codex_hooks_enabled():
    """Codex runs hooks.json only with `hooks = true` under [features]."""
    try:
        section = None
        for line in open(CODEX_CONFIG, encoding="utf-8"):
            stripped = line.strip()
            if stripped.startswith("["):
                section = stripped
            elif section == "[features]" and re.match(r"hooks\s*=\s*true\b", stripped):
                return True
    except OSError:
        pass
    return False


def codex_state():
    present = bool(shutil.which("codex")) or os.path.isdir(os.path.expanduser("~/.codex"))
    hooks = (read_json(CODEX_HOOKS) or {}).get("hooks") or {}
    path = command_path()
    ours = [h.get("command", "") for event in CODEX_EVENTS for entry in hooks.get(event) or []
            for h in entry.get("hooks") or [] if "baran push codex-hook" in h.get("command", "")]
    if not ours:
        state = "missing"
    elif len(ours) == len(CODEX_EVENTS) and all(c == f"{path} push codex-hook" for c in ours):
        # Hooks in the file do nothing until the feature is on.
        state = "installed" if codex_hooks_enabled() else "partial"
    else:
        state = "outdated"
    return {"id": "codex", "name": "Codex", "present": present, "state": state}


def integrate_codex(remove):
    data = read_json(CODEX_HOOKS)
    if data is None:
        if os.path.exists(CODEX_HOOKS):
            sys.exit("~/.codex/hooks.json is not valid JSON; not touching it")
        data = {}
    else:
        shutil.copy(CODEX_HOOKS, CODEX_HOOKS + ".bak-baran")
    hooks = data.setdefault("hooks", {})
    for event in CODEX_EVENTS:
        # Ours goes last, so the trust Codex keeps for other hooks by their
        # position stays valid.
        entries = [e for e in hooks.get(event) or []
                   if not any("baran push codex-hook" in h.get("command", "") for h in e.get("hooks") or [])]
        if not remove:
            entries.append({"hooks": [{"type": "command", "command": f"{command_path()} push codex-hook"}]})
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)
    os.makedirs(os.path.dirname(CODEX_HOOKS), exist_ok=True)
    with open(CODEX_HOOKS, "w", encoding="utf-8") as out:
        json.dump(data, out, indent=2, ensure_ascii=False)
        out.write("\n")


def pi_state():
    present = bool(shutil.which("pi")) or os.path.isdir(os.path.expanduser("~/.pi"))
    target = os.path.join(PI_EXTENSIONS, "baran-push.ts")
    if not os.path.exists(target):
        state = "missing"
    else:
        state = "installed" if filecmp.cmp(target, BUNDLED_PI, shallow=False) else "outdated"
    return {"id": "pi", "name": "pi", "present": present, "state": state}


def integrate_claude(remove):
    settings = read_json(CLAUDE_SETTINGS)
    if settings is None:
        if os.path.exists(CLAUDE_SETTINGS):
            sys.exit("~/.claude/settings.json is not valid JSON; not touching it")
        settings = {}
    else:
        shutil.copy(CLAUDE_SETTINGS, CLAUDE_SETTINGS + ".bak-baran")
    path = command_path()
    hooks = settings.setdefault("hooks", {})
    wanted = dict(CLAUDE_EVENTS)
    # Older versions hooked Notification; every event is cleaned of ours first.
    for event in list(hooks) + [e for e in wanted if e not in hooks]:
        entries = []
        for entry in hooks.get(event) or []:
            kept = [h for h in entry.get("hooks") or [] if "baran push claude-hook" not in h.get("command", "")]
            if kept:
                entries.append({**entry, "hooks": kept})
        matcher = wanted.get(event)
        if not remove and event in wanted:
            entry = {"hooks": [{"type": "command", "command": f"{path} push claude-hook"}]}
            if matcher:
                entry = {"matcher": matcher, **entry}
            entries.append(entry)
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    line = (settings.get("statusLine") or {}).get("command", "")
    if remove:
        if "baran statusline" in line:
            settings.pop("statusLine")
    elif not line or "baran statusline" in line:
        # Someone else's status line stays; the limits then just do not refresh.
        settings["statusLine"] = {"type": "command", "command": f"{path} statusline"}
    os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
    with open(CLAUDE_SETTINGS, "w", encoding="utf-8") as out:
        json.dump(settings, out, indent=2, ensure_ascii=False)
        out.write("\n")


def integrate_pi(remove):
    target = os.path.join(PI_EXTENSIONS, "baran-push.ts")
    if remove:
        if os.path.exists(target):
            os.remove(target)
        return
    os.makedirs(PI_EXTENSIONS, exist_ok=True)
    shutil.copy(BUNDLED_PI, target)


def report():
    current = version()
    newest = latest()
    return {
        "version": current,
        "latest": newest,
        "install": install_kind(),
        "update_command": update_command(),
        "checks": checks(),
        "integrations": [claude_state(), codex_state(), pi_state()],
    }


def doctor(arguments):
    data = report()
    if "--json" in arguments:
        print(json.dumps(data, ensure_ascii=False))
        return 0
    newer = data["latest"] and newer_than(data["latest"], data["version"])
    print(f"baran {data['version']}" + (f" (newest {data['latest']})" if newer else ""))
    for item in data["checks"]:
        print(("  ok   " if item["ok"] else "  --   ") + f"{item['title']}: {item['detail']}")
    for item in data["integrations"]:
        print(f"  {item['state']:9} {item['name']}" + ("" if item["present"] else " (not found here)"))
    return 0


def integrate(arguments):
    names = [a for a in arguments if not a.startswith("-")]
    actions = {"claude": (integrate_claude, claude_state), "codex": (integrate_codex, codex_state),
               "pi": (integrate_pi, pi_state)}
    if len(names) != 1 or names[0] not in actions:
        print("usage: baran integrate claude|codex|pi [--remove]", file=sys.stderr)
        return 2
    change, state = actions[names[0]]
    change("--remove" in arguments)
    print(f"{names[0]}: {state()['state']}")
    if names[0] == "codex" and "--remove" not in arguments:
        print("If Codex asks on its next start, trust the new hooks." if codex_hooks_enabled()
              else "Turn hooks on in ~/.codex/config.toml: [features] hooks = true")
    return 0


if __name__ == "__main__":
    mode, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("doctor", [])
    if "--help" in rest or "-h" in rest:
        print(__doc__.strip())
        sys.exit(0)
    sys.exit(integrate(rest) if mode == "integrate" else doctor(rest))
