#!/usr/bin/env python3
"""Sends a push notification to the phones registered by the Baran iOS app.

No server in between: this talks to Apple's push service directly, with the
APNs key from the developer account.

  baran push send "Title" "Body"    send to every registered phone
  baran push notify "Title" "Body"  same, but silent while the Mac is in use
  baran push claude-hook            notify, fed by a Claude Code hook on stdin

Config, ~/.config/baran/apns.json:
  {"team_id": "ABCDE12345", "key_id": "XYZ987ABCD", "key_path": "~/.config/baran/AuthKey_XYZ987ABCD.p8"}
Phones, ~/.config/baran/devices.json: written by the app over SSH.
Without either file the script does nothing and exits 0, so a hook never
breaks the agent.
"""
import base64
import json
import os
import subprocess
import sys
import time

BASE = os.path.expanduser("~/.config/baran")
TOKEN_LIFETIME = 40 * 60  # Apple rejects tokens older than 1 h and ones renewed too often.
AWAY_AFTER = 180  # Seconds without keyboard or mouse before the owner counts as away.


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def raw_signature(der):
    """ECDSA signature: ASN.1 DER SEQUENCE{r, s} -> fixed 32+32 bytes, as JWT wants."""
    at = 2 + (der[1] & 0x7F if der[1] & 0x80 else 0)
    parts = []
    for _ in range(2):
        length = der[at + 1]
        number = der[at + 2:at + 2 + length]
        parts.append(number.lstrip(b"\x00").rjust(32, b"\x00"))
        at += 2 + length
    return b"".join(parts)


def provider_token(config):
    cache = os.path.join(BASE, "jwt-cache.json")
    try:
        saved = json.load(open(cache))
        if saved["key_id"] == config["key_id"] and time.time() - saved["iat"] < TOKEN_LIFETIME:
            return saved["jwt"]
    except Exception:
        pass
    issued = int(time.time())
    head = b64url(json.dumps({"alg": "ES256", "kid": config["key_id"]}).encode())
    claims = b64url(json.dumps({"iss": config["team_id"], "iat": issued}).encode())
    signing_input = f"{head}.{claims}".encode()
    der = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", os.path.expanduser(config["key_path"])],
        input=signing_input, capture_output=True, check=True).stdout
    jwt = f"{head}.{claims}.{b64url(raw_signature(der))}"
    try:
        with open(os.open(cache, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
            json.dump({"key_id": config["key_id"], "iat": issued, "jwt": jwt}, out)
    except OSError:
        pass
    return jwt


def send(title, body):
    try:
        config = json.load(open(os.path.join(BASE, "apns.json")))
        devices = json.load(open(os.path.join(BASE, "devices.json")))
    except (OSError, ValueError):
        return 0
    if not devices:
        return 0
    jwt = provider_token(config)
    payload = json.dumps({"aps": {"alert": {"title": title, "body": body[:300]}, "sound": "default"}})
    gone, failed = [], 0
    for device in devices:
        host = "api.sandbox.push.apple.com" if device.get("env") == "sandbox" else "api.push.apple.com"
        result = subprocess.run(
            ["curl", "-sS", "--http2", "--max-time", "10", "-o", "-", "-w", "\n%{http_code}",
             "-H", f"authorization: bearer {jwt}",
             "-H", f"apns-topic: {device['bundle']}",
             "-H", "apns-push-type: alert",
             "-d", payload, f"https://{host}/3/device/{device['token']}"],
            capture_output=True, text=True)
        reply, _, status = result.stdout.rpartition("\n")
        if status == "200":
            continue
        failed += 1
        print(f"{device.get('name', 'phone')}: {status} {reply.strip() or result.stderr.strip()}", file=sys.stderr)
        if status == "410" or "BadDeviceToken" in reply:
            gone.append(device["token"])
    if gone:
        with open(os.path.join(BASE, "devices.json"), "w") as out:
            json.dump([d for d in devices if d["token"] not in gone], out, indent=1)
    return 1 if failed else 0


def at_the_mac():
    """True while the keyboard or mouse was touched recently: the reply is on screen anyway."""
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=5).stdout
        idle = next(int(line.split("=")[-1]) for line in out.splitlines() if "HIDIdleTime" in line)
    except Exception:
        return False
    return idle / 1e9 < AWAY_AFTER


def notify(title, body):
    return 0 if at_the_mac() else send(title, body)


def excerpt(text, limit=160):
    """The opening words of a reply, on one line, without markdown marks."""
    text = " ".join(text.replace("**", "").replace("`", "").replace("#", "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def last_reply(event):
    """What Claude said last: from the hook input, else from the end of the transcript."""
    said = event.get("last_assistant_message")
    if isinstance(said, str) and said.strip():
        return said
    try:
        with open(event["transcript_path"], "rb") as transcript:
            transcript.seek(0, os.SEEK_END)
            transcript.seek(max(0, transcript.tell() - 400_000))
            lines = transcript.read().decode("utf-8", "replace").splitlines()
    except (KeyError, OSError):
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        text = "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and part.get("type") == "text").strip()
        if text:
            return text
    return ""


def claude_hook():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    folder = os.path.basename(event.get("cwd") or "") or "Claude"
    if event.get("hook_event_name") == "Stop":
        return notify(f"Claude · {folder}", excerpt(last_reply(event)) or "Закінчив і чекає на вас.")
    return notify(f"Claude · {folder}", event.get("message") or "Потрібна ваша відповідь.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["send"] and len(sys.argv) == 4:
        sys.exit(send(sys.argv[2], sys.argv[3]))
    if sys.argv[1:2] == ["notify"] and len(sys.argv) == 4:
        sys.exit(notify(sys.argv[2], excerpt(sys.argv[3])))
    if sys.argv[1:2] == ["claude-hook"]:
        sys.exit(claude_hook())
    print(__doc__, file=sys.stderr)
    sys.exit(2)
