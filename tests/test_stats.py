"""python3 -m unittest discover -s tests"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libexec"))
import ports  # noqa: E402
import stats  # noqa: E402

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               10000.
Pages active:                            100000.
Pages inactive:                           50000.
Pages wired down:                         20000.
Pages occupied by compressor:             30000.
"""

NETSTAT = """Name       Mtu   Network       Address            Ipkts Ierrs     Ibytes    Opkts Oerrs     Obytes  Coll
lo0        16384 <Link#1>                         10     0       999       10     0       999     0
en0        1500  <Link#11>   aa:bb:cc:dd:ee:ff    50     0      5000       40     0      4000     0
en0        1500  192.168.1     192.168.1.5        50     -      5000       40     -      4000     -
utun3      1380  <Link#20>                         5     0        77        5     0        77     0
en1        1500  <Link#12>   aa:bb:cc:dd:ee:00     5     0       100        4     0        200     0
"""

LSOF = """p501
cnode
n*:5173
n127.0.0.1:9229
p777
csshd
n*:22
p900
cpython3.12
n[::1]:8000
"""

SS = """LISTEN 0 511 0.0.0.0:3000 0.0.0.0:* users:(("node",pid=4242,fd=20))
LISTEN 0 128 127.0.0.1:5432 0.0.0.0:*
LISTEN 0 511 [::]:8080 [::]:* users:(("python3",pid=17,fd=3))
"""


class StatsTest(unittest.TestCase):
    def test_mac_memory_counts_active_wired_and_compressed(self):
        outputs = {"sysctl": "51539607552\n", "vm_stat": VM_STAT}
        with mock.patch.object(stats, "run", lambda *c: outputs[c[0]]):
            memory = stats.memory_mac()
        self.assertEqual(memory, {"used": 150000 * 16384, "total": 51539607552, "available": 51539607552 - 150000 * 16384,
                                  "cache": None, "buffers": None})

    def test_mac_network_sums_real_interfaces_once(self):
        with mock.patch.object(stats, "run", lambda *c: NETSTAT):
            self.assertEqual(stats.network_mac(), {"received": 5100, "sent": 4200})

    def test_processes_sorted_by_cpu(self):
        out = (" 1.0  1000 /usr/bin/a\n 9.5  2000 /Applications/X.app/Contents/MacOS/Some Helper\n bad line\n"
               " 6.0   500 /usr/bin/a\n")
        with mock.patch.object(stats, "run", lambda *c: out):
            everything, top = stats.processes(limit=2)
        self.assertEqual(len(everything), 3)
        self.assertEqual(top, [{"name": "Some Helper", "count": 1, "cpu": 9.5, "memory": 2000 * 1024},
                               {"name": "a", "count": 2, "cpu": 7.0, "memory": 1500 * 1024}])

    def test_mac_swap(self):
        with mock.patch.object(stats, "run", lambda *c: "total = 4096.00M  used = 2867.25M  free = 1228.75M  (encrypted)\n"):
            self.assertEqual(stats.swap_mac(), {"used": 2867.25 * 1024 ** 2, "total": 4096 * 1024 ** 2})

    def test_linux_memory_and_swap(self):
        values = {"MemTotal": 8000, "MemAvailable": 6000, "Buffers": 200, "Cached": 2700, "SwapTotal": 2000, "SwapFree": 2000}
        self.assertEqual(stats.memory_linux(values),
                         {"used": 2000, "total": 8000, "available": 6000, "buffers": 200, "cache": 2700})
        self.assertEqual(stats.swap_linux(values), {"used": 0, "total": 2000})
        self.assertIsNone(stats.swap_linux({}))

    def test_cpu_usage_per_core(self):
        samples = iter([[(10, 100), (0, 100)], [(60, 200), (100, 200)]])
        with mock.patch.object(stats, "ticks_mac" if stats.MAC else "ticks_linux", lambda: next(samples)), \
                mock.patch.object(stats.time, "sleep"):
            overall, per_core = stats.cpu_usage()
        self.assertEqual(per_core, [0.5, 1.0])
        self.assertEqual(overall, 0.75)

    def test_report_has_every_field(self):
        data = stats.report()
        for key in ("cpu", "per_core", "cores", "memory", "swap", "network", "disk", "uptime", "processes",
                    "top_cpu", "top_memory", "process_count", "os", "cpu_model", "host", "time"):
            self.assertIn(key, data)


class PortsTest(unittest.TestCase):
    def test_lsof_fields(self):
        with mock.patch.object(ports, "run", lambda *c: LSOF):
            found = ports.from_lsof()
        self.assertEqual(found, [(5173, "*", "node", 501), (9229, "127.0.0.1", "node", 501),
                                 (22, "*", "sshd", 777), (8000, "::1", "python3.12", 900)])

    def test_ss_keeps_only_own_processes(self):
        with mock.patch.object(ports, "run", lambda *c: SS):
            found = ports.from_ss()
        self.assertEqual(found, [(3000, "0.0.0.0", "node", 4242), (8080, "::", "python3", 17)])

    def test_report_merges_skips_system_and_marks_reachable(self):
        with mock.patch.object(ports.shutil, "which", return_value="/usr/sbin/lsof"), \
                mock.patch.object(ports, "run", lambda *c: LSOF), \
                mock.patch.object(ports, "probe", lambda port, address: (port == 5173, "Vite" if port == 5173 else None)):
            found = ports.report()
        self.assertEqual([p["port"] for p in found], [5173, 8000, 9229])
        vite = found[0]
        self.assertEqual((vite["process"], vite["reachable"], vite["http"], vite["title"]), ("node", True, True, "Vite"))
        self.assertFalse(found[2]["reachable"])


if __name__ == "__main__":
    unittest.main()
