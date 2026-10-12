"""python3 -m unittest tests.test_attach (from the repo root)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libexec"))
import attach  # noqa: E402

LISTING = '{"sessions": [{"name": "default", "default": true, "running": true, "socket_path": "/x"},' \
          ' {"name": "realtor", "default": false, "running": false, "socket_path": null}]}'


class Done(Exception):
    pass


class AttachTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_run(command, **kwargs):
            self.calls.append(command)
            result = mock.Mock(returncode=0, stdout="")
            if command[1:3] == ["session", "list"]:
                result.stdout = "noise\n" + LISTING
            if command[:2] == ["launchctl", "managername"]:
                result.stdout = self.manager + "\n"
            return result

        self.manager = "Background"
        self.run = mock.patch.object(attach.subprocess, "run", side_effect=fake_run).start()
        self.exec = mock.patch.object(attach.os, "execv", side_effect=Done).start()
        mock.patch.object(attach, "herdr_path", return_value="/h/herdr").start()
        mock.patch.object(attach.sys, "platform", "darwin").start()
        mock.patch.dict(os.environ, {"TMPDIR": "/tmp"}).start()

    def tearDown(self):
        mock.patch.stopall()

    def bootstrapped(self):
        return [c for c in self.calls if c[:2] == ["launchctl", "bootstrap"]]

    def test_running_session_attaches_at_once(self):
        with self.assertRaises(Done):
            attach.main(["default"])
        self.assertEqual(self.bootstrapped(), [])
        self.exec.assert_called_with("/h/herdr", ["/h/herdr"])

    def test_stopped_session_outside_aqua_starts_in_the_gui_session(self):
        with mock.patch.object(attach.time, "sleep"), mock.patch.object(attach.time, "monotonic", side_effect=[0, 0, 10, 10]):
            with self.assertRaises(Done):
                attach.main(["realtor"])
        self.assertEqual(self.bootstrapped(), [["launchctl", "bootstrap", f"gui/{os.getuid()}",
                                                "/tmp/dev.bilokin.baran.herdr.realtor.plist"]])
        self.exec.assert_called_with("/h/herdr", ["/h/herdr", "--session", "realtor"])
        os.remove("/tmp/dev.bilokin.baran.herdr.realtor.plist")

    def test_inside_aqua_nothing_is_started(self):
        self.manager = "Aqua"
        with self.assertRaises(Done):
            attach.main(["realtor"])
        self.assertEqual(self.bootstrapped(), [])

    def test_elsewhere_than_macos_is_plain_herdr(self):
        mock.patch.object(attach.sys, "platform", "linux").start()
        with self.assertRaises(Done):
            attach.main(["realtor", "--handoff"])
        self.assertEqual([c for c in self.calls if c[0] == "launchctl"], [])
        self.exec.assert_called_with("/h/herdr", ["/h/herdr", "--session", "realtor", "--handoff"])

    def test_job_runs_the_server_of_that_session(self):
        job = attach.job_plist("l", "/h/herdr", "realtor")
        self.assertIn("HERDR_SESSION=realtor ", job["ProgramArguments"][2])
        self.assertNotIn("HERDR_SESSION", attach.job_plist("l", "/h/herdr", "default")["ProgramArguments"][2])


if __name__ == "__main__":
    unittest.main()
