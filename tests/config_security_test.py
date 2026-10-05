import unittest

from autonoma.config import GatewayConfig


class GatewayHostSecurityTest(unittest.TestCase):
    def test_accepts_loopback_hosts(self) -> None:
        for host in ("localhost", "127.0.0.1", "::1"):
            with self.subTest(host=host):
                self.assertEqual(GatewayConfig(host=host).host, host)

    def test_rejects_non_loopback_hosts(self) -> None:
        for host in ("0.0.0.0", "192.168.1.10", "example.com"):
            with self.subTest(host=host):
                with self.assertRaisesRegex(ValueError, "remote binding is disabled"):
                    GatewayConfig(host=host)