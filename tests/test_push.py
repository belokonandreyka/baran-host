"""python3 -m unittest discover -s tests"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libexec"))
import push  # noqa: E402


class PushKindTest(unittest.TestCase):
    def test_kind_rides_inside_the_box_only_when_set(self):
        self.assertEqual(json.loads(push.sealed_message("T", "B")), {"t": "T", "b": "B"})
        self.assertEqual(json.loads(push.sealed_message("T", "B", "ask"))["k"], "ask")

    def test_a_question_says_where_it_was_asked(self):
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p2", "HERDR_SOCKET_PATH": "/s.sock"}):
            asked = json.loads(push.sealed_message("T", "B", "ask", "HOST-ID"))
            done = json.loads(push.sealed_message("T", "B", None, "HOST-ID"))
        self.assertEqual((asked["h"], asked["p"], asked["s"]), ("HOST-ID", "w1:p2", "/s.sock"))
        self.assertEqual((done["h"], done["p"], done["s"]), ("HOST-ID", "w1:p2", "/s.sock"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertNotIn("p", json.loads(push.sealed_message("T", "B", "ask", "HOST-ID")))

    def test_direct_path_marks_questions_time_sensitive(self):
        self.assertNotIn("interruption-level", json.loads(push.direct_payload("T", "B"))["aps"])
        aps = json.loads(push.direct_payload("T", "B", "ask"))["aps"]
        self.assertEqual(aps["interruption-level"], "time-sensitive")

    def test_cli_reads_an_optional_kind(self):
        self.assertEqual(push.split_kind(["--kind", "ask", "T", "B"]), ("ask", ["T", "B"]))
        self.assertEqual(push.split_kind(["T", "B"]), (None, ["T", "B"]))

    def hook(self, function, event, at_the_mac=False, calls=None):
        calls = [] if calls is None else calls
        record = lambda *args, **kw: calls.append((function, args, kw)) or 0  # noqa: E731
        with mock.patch.object(push, "send", side_effect=lambda t, b, only_always=False, kind=None:
                                  record(t, b, kind=kind, only_always=only_always)), \
                mock.patch.object(push, "at_the_mac", return_value=at_the_mac), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(event))):
            getattr(push, function)()
        return calls[0][2].get("kind")

    def test_waiting_hooks_send_ask_and_stop_does_not(self):
        ask = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "cwd": "/x",
               "tool_input": {"questions": [{"question": "Which?"}]}}
        self.assertEqual(self.hook("claude_hook", ask), "ask")
        self.assertEqual(self.hook("claude_hook", {"hook_event_name": "PermissionRequest", "cwd": "/x"}), "ask")
        self.assertEqual(self.hook("codex_hook", {"hook_event_name": "PermissionRequest", "cwd": "/x"}), "ask")
        stop = {"hook_event_name": "Stop", "cwd": "/x", "last_assistant_message": "done"}
        self.assertIsNone(self.hook("claude_hook", stop))

    def test_questions_are_not_silenced_at_the_mac(self):
        for function in ("claude_hook", "codex_hook"):
            calls = []
            self.hook(function, {"hook_event_name": "PermissionRequest", "cwd": "/x"}, at_the_mac=True, calls=calls)
            self.assertFalse(calls[0][2]["only_always"], function)
        calls = []
        self.hook("codex_hook", {"hook_event_name": "Stop", "cwd": "/x"}, at_the_mac=True, calls=calls)
        self.assertTrue(calls[0][2]["only_always"])


if __name__ == "__main__":
    unittest.main()
