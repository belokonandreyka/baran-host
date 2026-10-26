"""python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libexec"))
import doctor  # noqa: E402


class StatusLineTest(unittest.TestCase):
    def test_a_script_that_runs_baran_statusline_counts_as_ours(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as script:
            script.write("#!/bin/sh\nprintf '%s' \"$IN\" | /opt/homebrew/bin/baran statusline >/dev/null\n")
        self.addCleanup(os.remove, script.name)
        self.assertTrue(doctor.calls_baran_statusline(script.name))
        self.assertTrue(doctor.calls_baran_statusline(f"'{script.name}' --compact"))

    def test_other_lines_do_not(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as script:
            script.write("#!/bin/sh\necho hi\n")
        self.addCleanup(os.remove, script.name)
        self.assertFalse(doctor.calls_baran_statusline(script.name))
        self.assertFalse(doctor.calls_baran_statusline("npx ccstatusline"))
        self.assertFalse(doctor.calls_baran_statusline(""))


if __name__ == "__main__":
    unittest.main()
