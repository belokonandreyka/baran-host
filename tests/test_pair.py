"""python3 -m unittest tests.test_pair (from the repo root)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "libexec"))
import pair  # noqa: E402

MAC_WITH_PROXY = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet6 fe80::1c%en0 prefixlen 64 secured scopeid 0xe
\tinet 192.168.1.23 netmask 0xffffff00 broadcast 192.168.1.255
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 9000
\tinet 198.18.0.1 --> 198.18.0.1 netmask 0xffff0000
utun5: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280
\tinet 100.101.102.103 --> 100.101.102.103 netmask 0xffffffff
"""

LINUX = """1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever
2: tailscale0    inet 100.90.1.2/32 scope global tailscale0\\       valid_lft forever
3: eth0    inet 10.0.0.5/24 brd 10.0.0.255 scope global eth0\\       valid_lft forever
4: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever
"""


def runner(outputs):
    def run(command, **kwargs):
        text = outputs.get(command[0])
        if text is None:
            raise FileNotFoundError(command[0])
        return mock.Mock(stdout=text)
    return run


class LocalAddressTest(unittest.TestCase):
    def test_wifi_wins_over_a_proxy_tunnel_and_tailscale(self):
        with mock.patch.object(pair.subprocess, "run", runner({"ifconfig": MAC_WITH_PROXY})):
            self.assertEqual(pair.local_address(), "192.168.1.23")

    def test_linux_lan_before_tailscale_and_docker_skipped(self):
        with mock.patch.object(pair.subprocess, "run", runner({"ip": LINUX})):
            self.assertEqual(pair.local_address(), "10.0.0.5")

    def test_only_a_proxy_tunnel_falls_back_to_the_host_name(self):
        tunnel_only = "utun4: flags=8051<UP> mtu 9000\n\tinet 198.18.0.1 --> 198.18.0.1 netmask 0xffff0000\n"
        probe = mock.MagicMock()
        probe.getsockname.return_value = ("198.18.0.1", 0)
        with mock.patch.object(pair.subprocess, "run", runner({"ifconfig": tunnel_only})), \
                mock.patch.object(pair.socket, "socket", return_value=probe), \
                mock.patch.object(pair.socket, "gethostname", return_value="MacBook-Air.local"):
            self.assertEqual(pair.local_address(), "MacBook-Air.local")

    def test_tailscale_when_nothing_else(self):
        only = "utun5: flags=8051<UP> mtu 1280\n\tinet 100.101.102.103 --> 100.101.102.103 netmask 0xffffffff\n"
        with mock.patch.object(pair.subprocess, "run", runner({"ifconfig": only})):
            self.assertEqual(pair.local_address(), "100.101.102.103")


if __name__ == "__main__":
    unittest.main()
