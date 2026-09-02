import os
import time
import unittest
from unittest import mock

from jarvis_relay import RelayConfig, RelayHandler, magic_packet


def _config(**env):
    """A RelayConfig built from a controlled environment."""
    base = {"JARVIS_APP_TOKEN": "t" * 32}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return RelayConfig("127.0.0.1", 8787)


class WakeGateTests(unittest.TestCase):
    """Wake-on-LAN is a LAN-only capability; a cloud relay must not pretend."""

    def test_wake_enabled_when_mac_configured(self):
        self.assertTrue(_config(JARVIS_MAC_ADDRESS="aa:bb:cc:dd:ee:ff").wake_enabled)

    def test_wake_disabled_without_mac_address(self):
        self.assertFalse(_config().wake_enabled)

    def test_wake_can_be_forced_off_for_cloud(self):
        cfg = _config(JARVIS_MAC_ADDRESS="aa:bb:cc:dd:ee:ff", JARVIS_WAKE_ENABLED="0")
        self.assertFalse(cfg.wake_enabled)

    def test_wake_can_be_forced_on(self):
        self.assertTrue(_config(JARVIS_WAKE_ENABLED="1").wake_enabled)

    def test_ensure_awake_returns_immediately_when_wake_disabled(self):
        """The whole point of item 2: no 90 s block on a hopeless request."""
        cfg = _config(JARVIS_WAKE_ENABLED="0", JARVIS_WAKE_TIMEOUT="90")
        handler = RelayHandler.__new__(RelayHandler)
        handler.config = cfg
        with mock.patch.object(RelayHandler, "_mac_online", return_value=False), \
             mock.patch.object(RelayHandler, "_wake") as wake:
            started = time.monotonic()
            result = handler._ensure_awake()
            elapsed = time.monotonic() - started
        self.assertFalse(result)
        self.assertLess(elapsed, 1.0, "must fail fast, not wait for wake_timeout")
        wake.assert_not_called()

    def test_ensure_awake_short_circuits_when_mac_already_online(self):
        cfg = _config(JARVIS_MAC_ADDRESS="aa:bb:cc:dd:ee:ff")
        handler = RelayHandler.__new__(RelayHandler)
        handler.config = cfg
        with mock.patch.object(RelayHandler, "_mac_online", return_value=True), \
             mock.patch.object(RelayHandler, "_wake") as wake:
            self.assertTrue(handler._ensure_awake())
        wake.assert_not_called()


class RelayTests(unittest.TestCase):
    def test_magic_packet(self):
        packet = magic_packet("AA:BB:CC:DD:EE:FF")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("AABBCCDDEEFF"))

    def test_invalid_mac(self):
        with self.assertRaises(ValueError):
            magic_packet("nope")


if __name__ == "__main__":
    unittest.main()
