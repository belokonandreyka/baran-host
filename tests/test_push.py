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
        # Inside a herdr-core terminal: its address, and "hc" in place of a socket.
        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t7"}, clear=True):
            core = json.loads(push.sealed_message("T", "B", "ask", "HOST-ID"))
        self.assertEqual((core["h"], core["p"], core["s"]), ("HOST-ID", "t7", "hc"))
        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t7", "HERDR_PANE_ID": "w1:p2"}, clear=True):
            self.assertEqual(json.loads(push.sealed_message("T", "B", "ask", "HOST-ID"))["p"], "w1:p2")

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
        with mock.patch.object(push, "send", side_effect=lambda t, b, only_always=False, kind=None, tool=None:
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


class AsksOnlyTest(unittest.TestCase):
    def test_a_phone_that_wants_only_questions_gets_no_done_push(self):
        devices = [{"relay": "r", "id": "all"}, {"relay": "r", "id": "asks", "asks_only": True}]
        for kind, expected in ((None, ["all"]), ("ask", ["all", "asks"])):
            sent = []
            with mock.patch.object(push, "quiet", return_value=False), \
                    mock.patch.object(push, "remember"), \
                    mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(devices))), \
                    mock.patch.object(push, "send_relayed",
                                      side_effect=lambda d, *a: sent.append(d["id"]) or (True, False)):
                push.send("T", "B", kind=kind)
            self.assertEqual(sent, expected, kind)


class ClearTest(unittest.TestCase):
    """A push leaves a mark; the answer takes it and tells the phones once."""

    def setUp(self):
        import tempfile
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        devices = [{"relay": "https://r", "id": "a", "secret": "s", "key": "AA=="}, {"token": "raw"}]
        with open(os.path.join(self.folder.name, "devices.json"), "w") as out:
            json.dump(devices, out)
        self.cleared = []
        for patch in (mock.patch.object(push, "BASE", self.folder.name),
                      mock.patch.object(push, "quiet", return_value=False),
                      mock.patch.object(push, "send_relayed", return_value=(True, False)),
                      mock.patch.object(push, "clear_relayed", side_effect=lambda d, t: self.cleared.append((d["id"], t))),
                      mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p1"})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_nothing_is_sent_when_nothing_waits(self):
        push.clear("Claude · x")
        self.assertEqual(self.cleared, [])

    def test_an_answer_clears_once_and_only_relayed_phones(self):
        push.send("Claude · x", "Asks: Which?", kind="ask")
        push.clear("Claude · x")
        push.clear("Claude · x")
        self.assertEqual(self.cleared, [("a", "Claude · x")])

    def test_another_tool_finishing_leaves_a_permission_request(self):
        push.send("Claude · x", "Needs permission: Bash rm", kind="ask", tool="Bash")
        push.clear("Claude · x", tool="Read")
        self.assertEqual(self.cleared, [])
        push.clear("Claude · x", tool="Bash")
        self.assertEqual(len(self.cleared), 1)

    def test_panes_do_not_clear_each_other(self):
        push.send("Claude · x", "done")
        with mock.patch.dict(os.environ, {"HERDR_PANE_ID": "w1:p2"}):
            push.clear("Claude · x")
        self.assertEqual(self.cleared, [])

    def test_claude_hooks_clear(self):
        push.send("Claude · x", "done")
        event = {"hook_event_name": "UserPromptSubmit", "cwd": "/x"}
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
            self.assertEqual(push.claude_hook(), 0)
        self.assertEqual(self.cleared, [("a", "Claude · x")])

    def test_the_clear_box_says_what_it_is(self):
        message = json.loads(push.sealed_message("Claude · x", "", "clear", "HOST"))
        self.assertEqual((message["k"], message["h"], message["p"]), ("clear", "HOST", "w1:p1"))


if __name__ == "__main__":
    unittest.main()
