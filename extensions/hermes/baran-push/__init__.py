"""Pushes to the Baran iOS app from interactive Hermes sessions (cli, at a
terminal): the reply when a turn ends, and a nudge when Hermes waits for an
approval or asks a clarifying question. Gateway turns (Telegram and the
like) already reach you there, and scripted `hermes chat -q` runs have no
terminal, so neither sends anything.

Interactive sessions are also noted in ~/.config/baran/hermes-sessions.json,
which is how the app's agents list finds them in Hermes' state.db.

Installed by `baran integrate hermes`, which fills in the path below.
"""
import json
import os
import subprocess
import sys
import threading
import time

BARAN = "@BARAN@"
# Which surface each session runs on, from the turn that started it.
_platforms = {}
_lock = threading.Lock()


def _push(mode, title, body):
    # Hermes waits for hooks; the push goes out on its own.
    def run():
        try:
            subprocess.run([BARAN, "push", mode, title, body[:300]], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=20, check=False)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


# Scripts and cron run Hermes without a terminal; only a person at one gets pushes.
_INTERACTIVE = sys.stdin.isatty()
_NOTES = os.path.expanduser("~/.config/baran/hermes-sessions.json")


def _note(session_id):
    """Remembers an interactive session for the app's agents list."""
    try:
        try:
            notes = json.load(open(_NOTES))
        except (OSError, ValueError):
            notes = []
        db = os.path.join(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"), "state.db")
        notes = [n for n in notes if n.get("id") != session_id][-49:]
        notes.append({"id": session_id, "db": db, "cwd": os.getcwd(), "t": time.time()})
        os.makedirs(os.path.dirname(_NOTES), exist_ok=True)
        with open(_NOTES + ".tmp", "w") as out:
            json.dump(notes, out)
        os.replace(_NOTES + ".tmp", _NOTES)
    except OSError:
        pass


def _title():
    return "Hermes · " + (os.path.basename(os.getcwd()) or "~")


def _session(primary="", kwargs=None):
    kwargs = kwargs or {}
    return str(kwargs.get("session_id") or primary or kwargs.get("task_id") or "hermes")


def on_pre_llm_call(session_id="", platform="", **kwargs):
    key = _session(session_id, kwargs)
    with _lock:
        _platforms[key] = platform if _INTERACTIVE else "script"
    if _INTERACTIVE and platform == "cli":
        _note(key)


def on_post_llm_call(session_id="", assistant_response="", platform="", **kwargs):
    if _INTERACTIVE and platform == "cli" and isinstance(assistant_response, str):
        _push("notify", _title(), assistant_response.strip() or "Закінчив і чекає на вас.")


def on_pre_tool_call(tool_name="", args=None, **kwargs):
    if str(tool_name).strip().lower() != "clarify":
        return
    with _lock:
        platform = _platforms.get(_session(kwargs=kwargs))
    if platform == "cli":
        question = (args or {}).get("question") if isinstance(args, dict) else ""
        _push("send", _title(), "Питає: " + question if question else "Має до вас питання.")


def on_pre_approval_request(command="", surface="", **kwargs):
    if _INTERACTIVE and surface == "cli":
        _push("send", _title(), "Потрібен дозвіл: " + command if command else "Потрібен дозвіл.")


def register(ctx):
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("post_llm_call", on_post_llm_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("pre_approval_request", on_pre_approval_request)
