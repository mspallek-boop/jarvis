import json
import tempfile
import unittest
from pathlib import Path

from jarvis_bridge import BridgeConfig, constant_time_token_matches, load_env, parse_sse


class BridgeTests(unittest.TestCase):
    def test_token_comparison(self):
        self.assertTrue(constant_time_token_matches("abc", "abc"))
        self.assertFalse(constant_time_token_matches("abc", "abd"))
        self.assertFalse(constant_time_token_matches("", ""))

    def test_env_loader_does_not_override_existing_value(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("JARVIS_TEST_VALUE=from-file\n", encoding="utf-8")
            os.environ["JARVIS_TEST_VALUE"] = "from-shell"
            load_env(path)
            self.assertEqual(os.environ["JARVIS_TEST_VALUE"], "from-shell")

    def test_sse_parser_survives_non_dict_json(self):
        """A bare JSON list/string is valid JSON but has no .get(); it must be
        skipped, not crash the stream."""
        events = list(parse_sse(iter([
            b"data: [1,2]\n",
            b'data: "plain"\n',
            b'data: {"ok":true}\n',
        ])))
        self.assertEqual(events, [("", {"ok": True})])

    def test_sse_parser_handles_unicode_and_bad_json(self):
        lines = iter([
            b"event: assistant.delta\n",
            "data: {\"delta\":\"Grüße\"}\n".encode(),
            b"data: nope\n",
            b"event: run.completed\n",
            b"data: {\"usage\":{\"output_tokens\":2}}\n",
        ])
        events = list(parse_sse(lines))
        self.assertEqual(events[0], ("assistant.delta", {"delta": "Grüße"}))
        self.assertEqual(events[1][0], "run.completed")


class WakeRelayConfigTests(unittest.TestCase):
    """The /wake passthrough target must come only from the environment."""

    def setUp(self):
        import os
        # from_environment() refuses to build without a >=24 char app token.
        os.environ["JARVIS_APP_TOKEN"] = "x" * 32
        os.environ.pop("JARVIS_RELAY_URL", None)

    def tearDown(self):
        import os
        os.environ.pop("JARVIS_RELAY_URL", None)

    def test_relay_url_defaults_to_empty(self):
        cfg = BridgeConfig.from_environment("127.0.0.1", 8770)
        self.assertEqual(cfg.relay_url, "")

    def test_relay_url_read_from_environment_and_stripped(self):
        import os
        os.environ["JARVIS_RELAY_URL"] = "  http://relay.example:8787  "
        cfg = BridgeConfig.from_environment("127.0.0.1", 8770)
        self.assertEqual(cfg.relay_url, "http://relay.example:8787")


import http.client
import os
import threading
from http import HTTPStatus
from urllib.parse import quote

from jarvis_bridge import make_server


class BridgeHTTPTests(unittest.TestCase):
    """Tests that exercise the HTTP layer and the auth gate."""

    TOKEN = "test-app-token-0123456789abcdef"
    assert len(TOKEN) >= 24

    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.mkdtemp()
        cls._root = Path(cls._tmp_dir).resolve()
        os.environ["JARVIS_APP_TOKEN"] = cls.TOKEN
        os.environ["JARVIS_RELAY_URL"] = ""
        cls.config = BridgeConfig(
            host="127.0.0.1",
            port=0,
            hermes_url="http://127.0.0.1:1",  # nothing listens here
            hermes_key="test-hermes-key",
            app_token=cls.TOKEN,
            relay_url="",
            file_roots=(cls._root,),
            state_path=Path(cls._tmp_dir) / "sessions.json",
        )
        cls.server = make_server(cls.config)
        cls.host, cls.port = cls.server.server_address[:2]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        os.environ.pop("JARVIS_APP_TOKEN", None)
        os.environ.pop("JARVIS_RELAY_URL", None)
        import shutil
        shutil.rmtree(cls._tmp_dir, ignore_errors=True)

    def _request(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            data = None
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        conn.close()
        return response.status, payload

    def test_root_returns_service_info_without_token(self):
        status, payload = self._request("GET", "/")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("JARVIS Bridge", payload)

    def test_health_requires_token(self):
        status, _ = self._request("GET", "/health")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_health_rejects_wrong_token(self):
        status, _ = self._request("GET", "/health", token="wrong-token")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_wake_requires_token(self):
        status, _ = self._request("POST", "/wake", body={})
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_wake_returns_local_response_without_relay(self):
        status, payload = self._request("POST", "/wake", body={}, token=self.TOKEN)
        self.assertEqual(status, HTTPStatus.OK)
        data = json.loads(payload)
        self.assertEqual(data, {"awake": True, "relay": False})

    def test_unknown_path_returns_404_with_valid_token(self):
        status, _ = self._request("POST", "/nope", body={"anything": "ok"}, token=self.TOKEN)
        self.assertEqual(status, HTTPStatus.NOT_FOUND)

    def test_files_rejects_traversal(self):
        # A classic ../ traversal must never escape the configured roots.
        traversal = "../" * 8 + "etc/passwd"
        qs_path = quote(traversal, safe="")
        status, _ = self._request("GET", f"/files?path={qs_path}", token=self.TOKEN)
        self.assertIn(status, (HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
                      f"traversal returned {status}, expected 403 or 404")


if __name__ == "__main__":
    unittest.main()
