#!/usr/bin/env python3
"""Fetches upstream in git folders so ahead/behind counts stay current.

  baran fetch DIR...

Run by the app, in the background, for the folders it shows. Does nothing
unless the git_fetch setting is on; a repository fetched in the last five
minutes is skipped. Git never prompts: a remote that needs a password or an
unknown host key is left alone.
"""
import os
import subprocess
import sys
import time

import settings

EVERY = 5 * 60
# Ours, beside git's own files: FETCH_HEAD is left as git keeps it.
MARKER = "baran-fetched"


def root(folder):
    result = subprocess.run(["git", "-C", folder, "rev-parse", "--absolute-git-dir"],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def stale(git_dir, now=None):
    """True when the last fetch is older than five minutes (or never ran)."""
    try:
        fetched = os.path.getmtime(os.path.join(git_dir, MARKER))
    except OSError:
        return True
    return (now or time.time()) - fetched >= EVERY


def fetch(git_dir):
    # Touched first, so a second call in the meantime does not fetch again.
    marker = os.path.join(git_dir, MARKER)
    try:
        with open(marker, "a"):
            os.utime(marker)
    except OSError:
        return
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes",
               GIT_ASKPASS="true", SSH_ASKPASS="true")
    try:
        subprocess.run(["git", "--git-dir", git_dir, "fetch", "--quiet", "--prune"],
                       env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        pass


def main(folders):
    if not settings.load()["git_fetch"]:
        return 0
    seen = set()
    for folder in folders:
        git_dir = root(folder)
        if git_dir and git_dir not in seen and stale(git_dir):
            seen.add(git_dir)
            fetch(git_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
