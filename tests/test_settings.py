"""python3 -m unittest discover -s tests"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libexec"))
import fetch  # noqa: E402
import push  # noqa: E402
import settings  # noqa: E402


class HostDir(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        patch = mock.patch.object(settings, "BASE", self.base)
        patch.start()
        self.addCleanup(patch.stop)


class SettingsTest(HostDir):
    def test_defaults_until_set_and_set_keeps_the_rest(self):
        self.assertEqual(settings.load(), settings.DEFAULTS)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(settings.main(["set", "git_fetch", "on"]), 0)
        self.assertTrue(json.loads(out.getvalue())["git_fetch"])
        self.assertEqual(settings.load(), dict(settings.DEFAULTS, git_fetch=True))

    def test_unknown_names_and_values_are_refused(self):
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(settings.main(["set", "nope", "on"]), 2)
            self.assertEqual(settings.main(["set", "git_fetch", "yes"]), 2)

    def test_a_broken_file_counts_as_empty(self):
        with open(settings.path(), "w") as out:
            out.write("{")
        self.assertEqual(settings.load(), settings.DEFAULTS)


class QuietTest(HostDir):
    def quiet(self, kind=None, env=None, lines=()):
        with mock.patch.dict(os.environ, env or {}, clear=True), \
                mock.patch.object(push, "ancestors", return_value=list(lines)):
            return push.quiet(kind)

    def test_nested_agents_by_their_ancestry(self):
        self.assertFalse(push.nested(["sh -c baran push claude-hook", "claude", "-zsh", "herdr server"]))
        self.assertTrue(push.nested(["sh -c baran push claude-hook", "claude -p fix it",
                                     "bash -c claude -p fix it", "node /opt/homebrew/bin/pi", "-zsh"]))
        self.assertFalse(push.nested(["codex", "node /Users/a/pi-harness/run.js"]))

    def test_subagents_quiet_by_default_questions_never(self):
        nested = ["claude", "node /usr/local/bin/pi"]
        self.assertTrue(self.quiet(lines=nested))
        self.assertFalse(self.quiet("ask", lines=nested))
        self.assertTrue(self.quiet(env={"PI_COLLAB_SUBAGENT_DEPTH": "1"}))
        settings.save(dict(settings.DEFAULTS, quiet_subagents=False))
        self.assertFalse(self.quiet(lines=nested))

    def test_outside_herdr_only_when_turned_on(self):
        self.assertFalse(self.quiet(lines=["claude"]))
        settings.save(dict(settings.DEFAULTS, quiet_outside_herdr=True))
        self.assertTrue(self.quiet(lines=["claude"]))
        self.assertFalse(self.quiet(env={"HERDR_PANE_ID": "w1:p1"}, lines=["claude"]))
        self.assertFalse(self.quiet("ask", lines=["claude"]))

    def test_a_quiet_push_reaches_no_phone(self):
        settings.save(dict(settings.DEFAULTS, quiet_outside_herdr=True))
        with open(os.path.join(self.base, "devices.json"), "w") as out:
            json.dump([{"id": "d", "secret": "s", "key": "", "relay": "https://relay"}], out)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(push, "ancestors", return_value=[]), \
                mock.patch.object(push, "BASE", self.base), \
                mock.patch.object(push, "send_relayed", side_effect=AssertionError("sent")) as relayed:
            self.assertEqual(push.send("T", "B"), 0)
            with self.assertRaises(AssertionError):
                push.send("T", "B", kind="ask")
        self.assertEqual(relayed.call_count, 1)


class FetchTest(HostDir):
    def repo(self):
        folder = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", folder], check=True)
        return folder

    def test_does_nothing_while_off(self):
        with mock.patch.object(fetch, "fetch") as fetched:
            fetch.main([self.repo()])
        fetched.assert_not_called()

    def test_fetches_each_repository_once_then_waits_five_minutes(self):
        settings.save(dict(settings.DEFAULTS, git_fetch=True))
        folder = self.repo()
        os.makedirs(os.path.join(folder, "sub"))
        with mock.patch.object(subprocess, "run", wraps=subprocess.run) as run:
            fetch.main([folder, os.path.join(folder, "sub"), tempfile.mkdtemp()])
            fetches = [c for c in run.call_args_list if "fetch" in c.args[0]]
            self.assertEqual(len(fetches), 1)
            self.assertEqual(fetches[0].kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            fetch.main([folder])
            self.assertEqual(len([c for c in run.call_args_list if "fetch" in c.args[0]]), 1)
        git_dir = os.path.join(folder, ".git")
        self.assertFalse(fetch.stale(git_dir))
        self.assertTrue(fetch.stale(git_dir, now=time.time() + fetch.EVERY))


if __name__ == "__main__":
    unittest.main()
