"""baran attach [SESSION]: attach to a herdr session, starting its server where Keychain works.

On a Mac, a herdr server started from an SSH or mosh shell lives in that
shell's Background session, and so does every pane it spawns: Keychain reads
there fail with errSecInteractionNotAllowed, so Claude Code answers "Not
logged in" and token helpers come back empty. When this shell is not in the
Aqua (GUI) session and the session's server is not running yet, the server is
started as a launchd job in gui/<uid>, which is Aqua; then herdr attaches as
usual. Elsewhere this is plain `herdr --session SESSION`.
"""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time


def herdr_path():
    return shutil.which("herdr") or next(
        (p for p in (os.path.expanduser("~/.local/bin/herdr"), "/opt/homebrew/bin/herdr") if os.path.exists(p)),
        None)


def running(herdr, name):
    try:
        output = subprocess.run([herdr, "session", "list", "--json"], capture_output=True, text=True, timeout=10).stdout
        sessions = json.loads(output[output.index("{"):output.rindex("}") + 1])["sessions"]
    except (ValueError, KeyError, subprocess.SubprocessError):
        return False
    return any(s.get("name") == name and s.get("running") for s in sessions)


def in_aqua():
    try:
        return subprocess.run(["launchctl", "managername"], capture_output=True, text=True, timeout=5).stdout.strip() == "Aqua"
    except (OSError, subprocess.SubprocessError):
        return True


def job_plist(label, herdr, name):
    # The default session is the one without HERDR_SESSION; a login shell
    # gives the server the same PATH and environment the user's panes get.
    env = "" if name == "default" else f"HERDR_SESSION={name} "
    return {"Label": label,
            "ProgramArguments": ["/bin/zsh", "-lc", f"cd ~ && {env}HERDR_STARTUP_CWD=$HOME exec {herdr} server"],
            "RunAtLoad": True, "AbandonProcessGroup": True}


def start_in_gui(herdr, name, wait=5.0):
    """Starts the session's server in the GUI session; True when it is running afterwards."""
    label = f"dev.bilokin.baran.herdr.{name}"
    path = os.path.join(os.environ.get("TMPDIR", "/tmp"), label + ".plist")
    with open(path, "wb") as f:
        plistlib.dump(job_plist(label, herdr, name), f)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    if subprocess.run(["launchctl", "bootstrap", domain, path], capture_output=True).returncode != 0:
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if running(herdr, name):
            return True
        time.sleep(0.1)
    return running(herdr, name)


def main(arguments):
    if arguments[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    name = arguments[0] if arguments else "default"
    herdr = herdr_path()
    if not herdr:
        print("baran attach: herdr is not installed (baran fix herdr)", file=sys.stderr)
        return 1
    if sys.platform == "darwin" and not in_aqua() and not running(herdr, name):
        if not start_in_gui(herdr, name):
            print(f"baran attach: could not start {name} in the GUI session; "
                  "attaching normally (no Keychain in its panes)", file=sys.stderr)
    command = [herdr] if name == "default" else [herdr, "--session", name]
    os.execv(herdr, command + arguments[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
