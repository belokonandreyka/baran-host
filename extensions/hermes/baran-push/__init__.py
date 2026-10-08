"""Pushes to the Baran iOS app from interactive (cli) Hermes sessions: the
reply when a turn ends, and a nudge when Hermes waits for an approval or
asks a clarifying question. Gateway turns (Telegram and the like) already
reach you there, so they send nothing.

Installed by `baran integrate hermes`, which fills in the path below.
"""
import os
import subprocess
import threading

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


def _title():
    return "Hermes · " + (os.path.basename(os.getcwd()) or "~")


def _session(primary="", kwargs=None):
    kwargs = kwargs or {}
    return str(kwargs.get("session_id") or primary or kwargs.get("task_id") or "hermes")


def on_pre_llm_call(session_id="", platform="", **kwargs):
    with _lock:
        _platforms[_session(session_id, kwargs)] = platform


def on_post_llm_call(session_id="", assistant_response="", platform="", **kwargs):
    if platform == "cli" and isinstance(assistant_response, str):
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
    if surface == "cli":
        _push("send", _title(), "Потрібен дозвіл: " + command if command else "Потрібен дозвіл.")


def register(ctx):
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("post_llm_call", on_post_llm_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("pre_approval_request", on_pre_approval_request)
