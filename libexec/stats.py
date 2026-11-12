#!/usr/bin/env python3
"""How busy this machine is, for the app's server view.

  baran stats [--json]

CPU per core from the kernel's tick counters over a quarter second (mach on
a Mac, /proc/stat on Linux); memory and swap from vm_stat/sysctl or
/proc/meminfo; network from the interface counters (bytes since boot: the
app turns two readings into a rate); the busiest programs of your own user
from `ps`, one line per program name.
"""
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

MAC = platform.system() == "Darwin"


def run(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def cores():
    return os.cpu_count() or 1


# CPU ------------------------------------------------------------------------

def ticks_mac():
    """[(busy, total)] per core from host_processor_info."""
    system = ctypes.CDLL("/usr/lib/libSystem.dylib")
    system.mach_host_self.restype = ctypes.c_uint
    count = ctypes.c_uint()
    info = ctypes.POINTER(ctypes.c_int)()
    size = ctypes.c_uint()
    # PROCESSOR_CPU_LOAD_INFO = 2: user, system, idle, nice per core.
    if system.host_processor_info(system.mach_host_self(), 2, ctypes.byref(count),
                                  ctypes.byref(info), ctypes.byref(size)) != 0:
        return None
    rows = []
    for core in range(count.value):
        user, sys_, idle, nice = (info[core * 4 + i] & 0xFFFFFFFF for i in range(4))
        rows.append((user + sys_ + nice, user + sys_ + nice + idle))
    return rows


def ticks_linux():
    rows = []
    try:
        with open("/proc/stat") as stat:
            for line in stat:
                if re.match(r"cpu\d+ ", line):
                    values = [int(v) for v in line.split()[1:]]
                    idle = values[3] + (values[4] if len(values) > 4 else 0)
                    rows.append((sum(values) - idle, sum(values)))
    except (OSError, ValueError):
        return None
    return rows


def cpu_usage(window=0.25):
    """(all cores 0…1, [each core 0…1]) over a short window."""
    sample = ticks_mac if MAC else ticks_linux
    try:
        first = sample()
        time.sleep(window)
        second = sample()
    except (OSError, AttributeError, ValueError):
        return None, None
    if not first or not second or len(first) != len(second):
        return None, None
    per_core, busy_all, total_all = [], 0, 0
    for (busy1, total1), (busy2, total2) in zip(first, second):
        busy, total = busy2 - busy1, total2 - total1
        per_core.append(round(max(0.0, min(1.0, busy / total)), 4) if total > 0 else 0.0)
        busy_all += busy
        total_all += total
    overall = round(max(0.0, min(1.0, busy_all / total_all)), 4) if total_all > 0 else None
    return overall, per_core


def cpu_model():
    if MAC:
        return run("sysctl", "-n", "machdep.cpu.brand_string").strip() or None
    try:
        with open("/proc/cpuinfo") as info:
            text = info.read()
    except OSError:
        return None
    found = re.search(r"^(?:Model|model name)\s*:\s*(.+)$", text, re.M)
    return found.group(1).strip() if found else None


# Memory ---------------------------------------------------------------------

def memory_mac():
    total = int(run("sysctl", "-n", "hw.memsize").strip() or 0)
    out = run("vm_stat")
    page = int((re.search(r"page size of (\d+)", out) or [0, 4096])[1])
    pages = {key.strip().lower(): int(value.strip().rstrip("."))
             for key, value in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", out, re.M)}
    used = sum(pages.get(key, 0) for key in ("pages active", "pages wired down", "pages occupied by compressor")) * page
    cache = pages.get("file-backed pages", 0) * page
    return {"used": used, "total": total, "available": max(0, total - used), "cache": cache or None, "buffers": None}


def swap_mac():
    out = run("sysctl", "-n", "vm.swapusage")
    def amount(name):
        found = re.search(name + r" = ([\d.,]+)([KMG])", out)
        if not found:
            return 0
        return float(found.group(1).replace(",", ".")) * {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[found.group(2)]
    return {"used": amount("used"), "total": amount("total")} if out else None


def meminfo():
    values = {}
    try:
        with open("/proc/meminfo") as info:
            for line in info:
                name, _, rest = line.partition(":")
                values[name] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {}
    return values


def memory_linux(values):
    if not values:
        return None
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return {"used": total - available, "total": total, "available": available,
            "buffers": values.get("Buffers"), "cache": values.get("Cached")}


def swap_linux(values):
    if "SwapTotal" not in values:
        return None
    return {"used": values["SwapTotal"] - values.get("SwapFree", 0), "total": values["SwapTotal"]}


# Network --------------------------------------------------------------------

def network_mac():
    """Received and sent bytes over the real interfaces (one Link row each)."""
    received = sent = 0
    seen = set()
    lines = run("netstat", "-ibn").splitlines()
    if not lines:
        return None
    header = lines[0].split()
    try:
        ibytes, obytes = header.index("Ibytes"), header.index("Obytes")
    except ValueError:
        return None
    for line in lines[1:]:
        parts = line.split()
        if len(parts) <= max(ibytes, obytes) - 1 or "<Link#" not in line:
            continue
        name = parts[0]
        if name in seen or name.startswith(("lo", "gif", "stf", "utun", "awdl", "llw", "bridge", "anpi", "ap")):
            continue
        seen.add(name)
        # A Link row without an address has one column fewer.
        shift = 0 if len(parts) == len(header) else -1
        try:
            received += int(parts[ibytes + shift])
            sent += int(parts[obytes + shift])
        except (ValueError, IndexError):
            continue
    return {"received": received, "sent": sent}


def network_linux():
    received = sent = 0
    try:
        with open("/proc/net/dev") as dev:
            for line in dev.readlines()[2:]:
                name, _, rest = line.partition(":")
                name = name.strip()
                if name == "lo" or name.startswith(("veth", "docker", "br-", "virbr")):
                    continue
                values = rest.split()
                received += int(values[0])
                sent += int(values[8])
    except (OSError, ValueError, IndexError):
        return None
    return {"received": received, "sent": sent}


# Processes ------------------------------------------------------------------

def ps_rows(*selection):
    rows = []
    for line in run("ps", *selection, "-o", "%cpu=,rss=,comm=").splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            cpu, rss = float(parts[0].replace(",", ".")), int(parts[1]) * 1024
        except ValueError:
            continue
        rows.append({"name": os.path.basename(parts[2].strip()) or parts[2].strip(), "cpu": cpu, "memory": rss})
    return rows


def programs(rows):
    """One line per program name: three node workers are `node ×3`."""
    merged = {}
    for row in rows:
        same = merged.setdefault(row["name"], {"name": row["name"], "count": 0, "cpu": 0.0, "memory": 0})
        same["count"] += 1
        same["cpu"] = round(same["cpu"] + row["cpu"], 1)
        same["memory"] += row["memory"]
    return list(merged.values())


def processes(limit=6):
    """(every process, your busiest programs by CPU) — the old shape, still sent."""
    everything = ps_rows("-A")
    own = programs(ps_rows("-U", str(os.getuid())))
    return everything, sorted(own, key=lambda row: row["cpu"], reverse=True)[:limit]


# Report ---------------------------------------------------------------------

def os_name():
    if MAC:
        return f"macOS {platform.mac_ver()[0]}".strip()
    return f"Linux {platform.release()}"


def uptime():
    if MAC:
        found = re.search(r"sec = (\d+)", run("sysctl", "-n", "kern.boottime"))
        return int(time.time() - int(found.group(1))) if found else None
    try:
        with open("/proc/uptime") as up:
            return int(float(up.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def report():
    cpu, per_core = cpu_usage()
    everything, top = processes()
    own = programs(ps_rows("-U", str(os.getuid())))
    values = {} if MAC else meminfo()
    try:
        disk = shutil.disk_usage("/System/Volumes/Data" if MAC and os.path.isdir("/System/Volumes/Data") else "/")
        disk = {"used": disk.used, "total": disk.total}
    except OSError:
        disk = None
    try:
        load = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load = None
    return {
        "time": time.time(),
        "host": platform.node().split(".")[0],
        "os": os_name(),
        "cpu_model": cpu_model(),
        "cpu": cpu,
        "per_core": per_core,
        "cores": cores(),
        "load": load,
        "memory": memory_mac() if MAC else memory_linux(values),
        "swap": swap_mac() if MAC else swap_linux(values),
        "network": network_mac() if MAC else network_linux(),
        "disk": disk,
        "uptime": uptime(),
        "process_count": len(everything),
        "processes": top,
        "top_cpu": sorted(own, key=lambda row: row["cpu"], reverse=True)[:3],
        "top_memory": sorted(own, key=lambda row: row["memory"], reverse=True)[:3],
    }


def human(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.0f} PB"


def main(arguments):
    if arguments not in ([], ["--json"]):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    data = report()
    if arguments:
        print(json.dumps(data))
        return 0
    print(f"{data['host']} · {data['os']} · {data['cpu_model'] or ''}")
    if data["cpu"] is not None:
        print(f"CPU     {data['cpu'] * 100:.0f}% of {data['cores']} cores")
    if data["memory"]:
        print(f"Memory  {human(data['memory']['used'])} of {human(data['memory']['total'])}")
    if data["swap"]:
        print(f"Swap    {human(data['swap']['used'])} of {human(data['swap']['total'])}")
    if data["disk"]:
        print(f"Disk    {human(data['disk']['used'])} of {human(data['disk']['total'])}")
    print(f"Processes {data['process_count']}; yours, busiest:")
    for row in data["top_cpu"]:
        print(f"  {row['cpu']:5.1f}%  {human(row['memory']):>7}  {row['name']} ×{row['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
