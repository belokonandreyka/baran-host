#!/usr/bin/env python3
"""Host settings the Baran app changes over SSH, kept in ~/.config/baran/settings.json.

  baran settings [--json]           show them
  baran settings set NAME on|off    change one

  quiet_subagents      no "finished" pushes from agents another agent started
  quiet_outside_herdr  no "finished" pushes from agents outside a herdr pane
  git_fetch            fetch upstream in the folders the app looks at, at most every 5 min

Questions and permission requests always go out.
"""
import json
import os
import sys

BASE = os.path.expanduser("~/.config/baran")
DEFAULTS = {"quiet_subagents": True, "quiet_outside_herdr": False, "git_fetch": False}


def path():
    return os.path.join(BASE, "settings.json")


def load():
    """The defaults with whatever the file sets on top; a broken file counts as empty."""
    try:
        with open(path()) as file:
            saved = json.load(file)
    except (OSError, ValueError):
        saved = {}
    return {name: bool(saved.get(name, value)) for name, value in DEFAULTS.items()}


def save(values):
    os.makedirs(BASE, exist_ok=True)
    temporary = path() + ".tmp"
    with open(temporary, "w") as out:
        json.dump(values, out, indent=1)
    os.replace(temporary, path())


def main(arguments):
    if arguments[:1] == ["set"] and len(arguments) == 3 and arguments[1] in DEFAULTS \
            and arguments[2] in ("on", "off"):
        values = load()
        values[arguments[1]] = arguments[2] == "on"
        save(values)
        arguments = ["--json"]
    if arguments in ([], ["--json"]):
        values = load()
        if arguments:
            print(json.dumps(values))
        else:
            for name, value in values.items():
                print(f"{name}: {'on' if value else 'off'}")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
