#!/usr/bin/env python3
"""Dev servers on this machine: TCP ports your own processes listen on.

  baran ports [--json]

Each port says who listens, on which address, and whether it answers HTTP
(with the page title when there is one). `reachable` means it listens on
every interface, so the phone can open it by the host's address; a port on
127.0.0.1 only works on the machine itself.
"""
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

# Not dev servers: the system's and our own tools' ports.
SKIP = {"sshd", "launchd", "rapportd", "ControlCe", "ControlCenter", "mDNSRespo", "cupsd", "sharingd",
        "identitys", "remoted", "systemd", "systemd-r", "rpcbind", "avahi-dae", "containerd", "dockerd"}


def run(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def from_lsof():
    """(port, address, process, pid) from lsof's field output, own processes only."""
    out = run("lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-u", str(os.getuid()), "-F", "pcn")
    found, pid, name = [], None, None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:]) if line[1:].isdigit() else None
        elif line.startswith("c"):
            name = line[1:]
        elif line.startswith("n"):
            address, _, port = line[1:].rpartition(":")
            if port.isdigit():
                found.append((int(port), address.strip("[]"), name or "", pid))
    return found


def from_ss():
    """The same from `ss` on Linux machines without lsof."""
    found = []
    for line in run("ss", "-ltnpH").splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        address, _, port = parts[3].rpartition(":")
        if not port.isdigit():
            continue
        user = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if not user:
            continue  # someone else's process: ss names only our own
        found.append((int(port), address.strip("[]").split("%")[0], user.group(1), int(user.group(2))))
    return found


def probe(port, address):
    """(answers HTTP, page title) with a quick GET /."""
    if address in ("*", "0.0.0.0", "") or address.startswith("127."):
        target = "127.0.0.1"
    elif address in ("::", "::1"):
        target = "::1"
    else:
        target = address
    try:
        connection = http.client.HTTPConnection(target, port, timeout=0.8)
        connection.request("GET", "/", headers={"User-Agent": "baran-ports", "Accept": "text/html"})
        response = connection.getresponse()
        body = response.read(65536).decode("utf-8", "replace")
        connection.close()
    except Exception:
        return False, None
    title = re.search(r"<title[^>]*>([^<]{1,120})</title>", body, re.I)
    return True, " ".join(title.group(1).split()) if title else None


def report():
    rows = from_lsof() if shutil.which("lsof") else from_ss()
    merged = {}
    for port, address, name, pid in rows:
        if name in SKIP or name.startswith(("com.apple", "Apple")):
            continue
        entry = merged.setdefault(port, {"port": port, "process": name, "pid": pid, "addresses": []})
        if address not in entry["addresses"]:
            entry["addresses"].append(address)
    ports = sorted(merged.values(), key=lambda entry: entry["port"])
    for entry in ports:
        entry["reachable"] = any(a in ("*", "0.0.0.0", "::") for a in entry["addresses"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda entry: probe(entry["port"], entry["addresses"][0]), ports)
    for entry, (http_ok, title) in zip(ports, results):
        entry["http"] = http_ok
        entry["title"] = title
    return ports


def main(arguments):
    if arguments not in ([], ["--json"]):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    ports = report()
    if arguments:
        print(json.dumps(ports))
        return 0
    for entry in ports:
        where = "all interfaces" if entry["reachable"] else ", ".join(entry["addresses"])
        kind = ("http" + (f" «{entry['title']}»" if entry["title"] else "")) if entry["http"] else "tcp"
        print(f"{entry['port']:>5}  {entry['process']:<16} {kind:<30} {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
