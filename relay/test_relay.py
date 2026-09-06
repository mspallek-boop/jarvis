import os
import io
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
             mock.patch.object(RelayHandler, "_wake") as wake, \
             mock.patch("jarvis_relay.time.sleep") as sleep:
            result = handler._ensure_awake()
        self.assertFalse(result)
        sleep.assert_not_called()
        wake.assert_not_called()

    def test_ensure_awake_short_circuits_when_mac_already_online(self):
        cfg = _config(JARVIS_MAC_ADDRESS="aa:bb:cc:dd:ee:ff")
        handler = RelayHandler.__new__(RelayHandler)
        handler.config = cfg
        with mock.patch.object(RelayHandler, "_mac_online", return_value=True), \
             mock.patch.object(RelayHandler, "_wake") as wake:
            self.assertTrue(handler._ensure_awake())
        wake.assert_not_called()


class RelayAuthAndStatusTests(unittest.TestCase):
    """Exercise real dispatch/auth with in-memory IO and no Mac or UDP traffic."""

    def handler(self, path, authorization=None, **env):
        handler = RelayHandler.__new__(RelayHandler)
        handler.config = _config(**env)
        handler.path = path
        handler.headers = {} if authorization is None else {"Authorization": authorization}
        handler.rfile = io.BytesIO()
        handler._json = mock.Mock()
        return handler

    def test_missing_or_wrong_token_cannot_probe_proxy_or_wake(self):
        for method, path in (("GET", "/health"), ("GET", "/files"),
                             ("POST", "/wake"), ("POST", "/chat"), ("POST", "/stop")):
            for token in (None, "Bearer wrong-token"):
                with self.subTest(method=method, path=path, token=token):
                    handler = self.handler(path, token)
                    with mock.patch.object(handler, "_mac_request") as upstream, \
                         mock.patch.object(handler, "_wake") as wake:
                        getattr(handler, "do_" + method)()
                    self.assertEqual(handler._json.call_args.args[0], 401)
                    upstream.assert_not_called()
                    wake.assert_not_called()

    def test_authorized_health_reports_mac_and_wake_capability(self):
        for online in (True, False):
            with self.subTest(online=online):
                handler = self.handler("/health", "Bearer " + "t" * 32)
                with mock.patch.object(handler, "_mac_online", return_value=online):
                    handler.do_GET()
                handler._json.assert_called_once_with(200, {
                    "ok": True, "relay": "online",
                    "mac": "online" if online else "sleeping_or_off",
                    "wake_enabled": False,
                })

    def test_authorized_wake_dispatches_once(self):
        handler = self.handler("/wake", "Bearer " + "t" * 32,
                               JARVIS_MAC_ADDRESS="aa:bb:cc:dd:ee:ff")
        with mock.patch.object(handler, "_wake") as wake:
            handler.do_POST()
        wake.assert_called_once_with()
        self.assertEqual(handler._json.call_args.args[0], 200)

    def test_cloud_wake_is_explicitly_unavailable(self):
        handler = self.handler("/wake", "Bearer " + "t" * 32, JARVIS_WAKE_ENABLED="0")
        with mock.patch.object(handler, "_wake") as wake:
            handler.do_POST()
        wake.assert_not_called()
        self.assertEqual(handler._json.call_args.args[0], 501)

    def test_cloud_chat_without_mac_does_not_proxy_or_wait(self):
        handler = self.handler("/chat", "Bearer " + "t" * 32, JARVIS_WAKE_ENABLED="0")
        with mock.patch.object(handler, "_mac_online", return_value=False), \
             mock.patch.object(handler, "_proxy") as proxy, \
             mock.patch("jarvis_relay.time.sleep") as sleep:
            handler.do_POST()
        proxy.assert_not_called()
        sleep.assert_not_called()
        self.assertEqual(handler._json.call_args.args[0], 503)

    def test_upstream_uses_only_app_token(self):
        handler = self.handler("/chat", "Bearer " + "t" * 32,
                               JARVIS_MAC_BRIDGE_URL="https://mac.example.ts.net:8443")
        with mock.patch("jarvis_relay.urllib.request.urlopen") as upstream:
            handler._mac_request("POST", "/chat", b"{}")
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, "https://mac.example.ts.net:8443/chat")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "t" * 32)
        self.assertEqual(request.data, b"{}")


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
