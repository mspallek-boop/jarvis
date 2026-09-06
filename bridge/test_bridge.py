import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from jarvis_bridge import (BridgeConfig, HermesClient, constant_time_token_matches,
                           load_env, parse_sse)


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


    def test_stop_without_any_id_is_a_400(self):
        status, payload = self._request("POST", "/stop", {}, token=self.TOKEN)
        self.assertEqual(status, 400)
        self.assertIn("client_run_id", json.loads(payload).get("error", ""))

    def test_stop_rejects_both_addressing_fields(self):
        status, payload = self._request(
            "POST", "/stop", {"run_id": "run_a", "client_run_id": "c1"}, token=self.TOKEN)
        self.assertEqual(status, 400)
        self.assertIn("schließen sich aus", json.loads(payload).get("error", ""))

    def test_stop_by_unknown_client_run_id_is_a_200_saying_so(self):
        status, payload = self._request(
            "POST", "/stop", {"client_run_id": "nope"}, token=self.TOKEN)
        self.assertEqual(status, 200)
        body = json.loads(payload)
        self.assertEqual(body.get("status"), "unknown")
        self.assertFalse(body.get("stopped"))

    def test_stop_rejects_a_malformed_client_run_id(self):
        status, _ = self._request(
            "POST", "/stop", {"client_run_id": "a/../b"}, token=self.TOKEN)
        self.assertEqual(status, 400)

    def test_stop_requires_token(self):
        status, _ = self._request("POST", "/stop", {"client_run_id": "c1"})
        self.assertEqual(status, 401)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SessionRecoveryTests(unittest.TestCase):
    """A lost session-state file must not brick every later turn.

    Regression: with no `jarvis-apple` entry on disk the bridge tried to create
    a session whose title Hermes already held, got 400, and answered 502 to the
    Apple apps forever.
    """

    def _client(self, directory):
        return HermesClient(BridgeConfig(
            host="127.0.0.1", port=8770,
            hermes_url="http://127.0.0.1:8642",
            hermes_key="unused-in-test", app_token="x" * 32,
            state_path=Path(directory) / "sessions.json",
        ))

    @staticmethod
    def _duplicate_title(listing, seen=None):
        """POST always 400s (duplicate title); GET returns `listing`."""
        def fake_request(method, path, payload=None, timeout=20):
            if seen is not None:
                seen.append((method, path))
            if method == "POST":
                raise urllib.error.HTTPError(path, 400, "invalid_title", None, None)
            return _FakeResponse(listing)
        return fake_request

    def test_duplicate_title_adopts_the_existing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "api_wanted", "title": "jarvis-apple", "source": "api_server"},
            ]})
            self.assertEqual(client._session_id("jarvis-apple"), "api_wanted")
            saved = json.loads(client.config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["jarvis-apple"], "api_wanted")

    def test_lookup_uses_exact_title_query_not_a_listing_scan(self):
        """The default listing is capped at 50 and hides old/hidden sessions,
        so the recovery must push the title into the query."""
        seen = []
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "api_wanted", "title": "jarvis-apple", "source": "api_server"},
            ]}, seen=seen)
            client._session_id("jarvis-apple")
        gets = [path for method, path in seen if method == "GET"]
        self.assertTrue(gets, "no GET was issued")
        self.assertIn("title=jarvis-apple", gets[0])
        self.assertIn("include_hidden=true", gets[0])

    def test_exact_title_match_is_required(self):
        """A substring hit from the gateway's search must not be adopted."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "api_other", "title": "jarvis-apple-smoke", "source": "api_server"},
            ]})
            with self.assertRaises(urllib.error.HTTPError):
                client._session_id("jarvis-apple")

    def test_api_owned_session_wins_over_a_foreign_one(self):
        """Hermes title uniqueness is global, so a CLI session can hold the
        name too; prefer the one this bridge could have created."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "cli_session", "title": "jarvis-apple", "source": "cli"},
                {"id": "api_session", "title": "jarvis-apple", "source": "api_server"},
            ]})
            self.assertEqual(client._session_id("jarvis-apple"), "api_session")

    def test_duplicate_title_with_no_match_still_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": []})
            with self.assertRaises(urllib.error.HTTPError):
                client._session_id("jarvis-apple")

    def test_non_400_errors_are_not_swallowed(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)

            def fake_request(method, path, payload=None, timeout=20):
                raise urllib.error.HTTPError(path, 500, "boom", None, None)

            client._request = fake_request
            with self.assertRaises(urllib.error.HTTPError) as caught:
                client._session_id("jarvis-apple")
            self.assertEqual(caught.exception.code, 500)

    def test_failure_during_recovery_lookup_is_surfaced_not_masked(self):
        """HTTPError subclasses URLError. A 401 on the recovery GET must not be
        reported as the earlier duplicate-title 400."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)

            def fake_request(method, path, payload=None, timeout=20):
                code = 400 if method == "POST" else 401
                raise urllib.error.HTTPError(path, code, "err", None, None)

            client._request = fake_request
            with self.assertRaises(urllib.error.HTTPError) as caught:
                client._session_id("jarvis-apple")
            self.assertEqual(caught.exception.code, 401)

    def test_malformed_session_id_is_rejected(self):
        """The id is interpolated into /api/sessions/{id}/chat/stream."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "../../etc/passwd", "title": "jarvis-apple", "source": "api_server"},
            ]})
            with self.assertRaises(RuntimeError):
                client._session_id("jarvis-apple")
            self.assertFalse(client.config.state_path.exists(),
                             "a malformed id must never reach the state file")

    def test_lookup_asks_for_children_and_a_full_page(self):
        """The gateway's title filter is substring-based and still capped by
        `limit`, and hides child sessions by default."""
        seen = []
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "api_wanted", "title": "jarvis-apple", "source": "api_server"},
            ]}, seen=seen)
            client._session_id("jarvis-apple")
        get = [path for method, path in seen if method == "GET"][0]
        self.assertIn("include_children=true", get)
        self.assertIn("limit=200", get)

    def test_foreign_source_only_refuses_instead_of_mixing_transcripts(self):
        """Hermes title uniqueness is global. Adopting a CLI-owned session would
        write the phone's messages into an unrelated transcript."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "cli_session", "title": "jarvis-apple", "source": "cli"},
            ]})
            with self.assertRaises(RuntimeError) as caught:
                client._session_id("jarvis-apple")
            self.assertIn("cli_session", str(caught.exception))
            self.assertFalse(client.config.state_path.exists())

    def test_transport_failure_in_lookup_is_not_reported_as_the_400(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)

            def fake_request(method, path, payload=None, timeout=20):
                if method == "POST":
                    raise urllib.error.HTTPError(path, 400, "invalid_title", None, None)
                raise urllib.error.URLError("connection refused")

            client._request = fake_request
            with self.assertRaises(RuntimeError) as caught:
                client._session_id("jarvis-apple")
            self.assertIn("lookup failed", str(caught.exception))

    def test_trailing_newline_id_is_rejected(self):
        """`$` matches before a trailing newline; fullmatch is required."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "api_ok\n", "title": "jarvis-apple", "source": "api_server"},
            ]})
            with self.assertRaises(RuntimeError):
                client._session_id("jarvis-apple")

    def test_malformed_cached_id_is_not_trusted(self):
        """An id written by an older build is interpolated into a URL path too."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client.config.state_path.write_text(
                json.dumps({"jarvis-apple": "../../etc/passwd"}), encoding="utf-8")
            client._request = self._duplicate_title({"object": "list", "data": [
                {"id": "api_clean", "title": "jarvis-apple", "source": "api_server"},
            ]})
            self.assertEqual(client._session_id("jarvis-apple"), "api_clean")

    def test_cancel_addresses_only_the_callers_own_run(self):
        """The conversation is shared. Cancelling by conversation name could
        stop another surface's turn, so only a client_run_id is accepted."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            with client._active_runs_lock:
                client._client_runs["mine"] = {"run_id": "run_mine", "cancelled": False}
            stopped = []
            client.stop = lambda rid: stopped.append(rid) or {"status": "stopped"}
            result = client.cancel_client_run("mine")
            self.assertEqual(stopped, ["run_mine"])
            self.assertTrue(result["stopped"])
            # somebody else's turn is untouched and unaddressable
            self.assertEqual(client.cancel_client_run("theirs")["status"], "unknown")

    def test_cancel_before_run_started_is_remembered(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            with client._active_runs_lock:
                client._client_runs["mine"] = {"cancelled": False}
            result = client.cancel_client_run("mine")
            self.assertEqual(result["status"], "pending")
            self.assertFalse(result["stopped"])
            with client._active_runs_lock:
                self.assertTrue(client._client_runs["mine"]["cancelled"])

    def test_stopping_is_not_reported_as_stopped(self):
        """Hermes answers 'stopping': it accepted an interrupt, it did not prove
        the run is dead."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            with client._active_runs_lock:
                client._client_runs["mine"] = {"run_id": "run_mine", "cancelled": False}
            client.stop = lambda rid: {"status": "stopping"}
            result = client.cancel_client_run("mine")
            self.assertEqual(result["status"], "stopping")
            self.assertFalse(result["stopped"])

    def test_stop_rejects_a_malformed_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            with self.assertRaises(ValueError):
                client.stop("../../v1/runs/other/stop")

    def test_failed_run_unbinds_the_dead_run(self):
        """run.failed raises out of the stream. A surviving entry would let a
        later cancel address a dead run."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client.config.state_path.write_text(
                json.dumps({"jarvis-apple": "api_ok"}), encoding="utf-8")
            sse = [
                b'event: run.started\n', b'data: {"run_id":"run_live"}\n',
                b'event: run.failed\n', b'data: {"error":"boom"}\n',
            ]

            class _Stream:
                def __enter__(self):
                    return iter(sse)

                def __exit__(self, *exc):
                    return False

            import unittest.mock as mock
            with mock.patch("urllib.request.urlopen", return_value=_Stream()):
                with self.assertRaises(RuntimeError):
                    client._chat_once("hi", "jarvis-apple", False, "mine")
            with client._active_runs_lock:
                entry = client._client_runs.get("mine")
            # The entry survives (chat() owns its lifetime and retries once on
            # 404) but the dead run must be unbound so a later cancel cannot
            # address it.
            self.assertIsNotNone(entry)
            self.assertNotIn("run_id", entry)

    def test_duplicate_client_run_id_is_rejected(self):
        """Two callers sharing one id could cancel each other and pop each
        other's bookkeeping."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            with client._active_runs_lock:
                client._client_runs["dup"] = {"cancelled": False}
            with self.assertRaises(ValueError):
                client.chat("hi", "jarvis-apple", "dup")
            # the first caller's entry survives the rejection
            with client._active_runs_lock:
                self.assertIn("dup", client._client_runs)

    def test_chat_removes_the_entry_when_the_turn_ends(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client._chat_once = lambda *a, **k: {"text": "ok", "tools": [], "run_id": "r"}
            client.chat("hi", "jarvis-apple", "mine")
            with client._active_runs_lock:
                self.assertNotIn("mine", client._client_runs)

    def test_cancel_during_session_recovery_survives_the_404_retry(self):
        """chat() retries once on 404. A cancel that landed during the first
        attempt must not be forgotten by the retry."""
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            calls = {"n": 0}

            def fake_chat_once(text, conversation, force_new, client_run_id=""):
                calls["n"] += 1
                if calls["n"] == 1:
                    with client._active_runs_lock:
                        client._client_runs[client_run_id]["cancelled"] = True
                    raise urllib.error.HTTPError("/x", 404, "gone", None, None)
                with client._active_runs_lock:
                    self.assertTrue(client._client_runs[client_run_id]["cancelled"],
                                    "the retry lost the pending cancellation")
                return {"text": "", "tools": [], "run_id": ""}

            client._chat_once = fake_chat_once
            client.chat("hi", "jarvis-apple", "mine")
            self.assertEqual(calls["n"], 2)

    def test_cached_conversation_makes_no_network_call(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            client.config.state_path.write_text(
                json.dumps({"jarvis-apple": "api_cached"}), encoding="utf-8")

            def explode(*a, **k):
                raise AssertionError("cached lookup must not hit the gateway")

            client._request = explode
            self.assertEqual(client._session_id("jarvis-apple"), "api_cached")


if __name__ == "__main__":
    unittest.main()
