import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.monitoring import WorkerMonitorStore
from kalshi_research_bot.paper_server import PaperHandler


def _request(url, *, username=None, password=None):
    headers = {}
    if username is not None:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode())


class InternalEndpointTests(unittest.TestCase):
    def test_internal_status_is_admin_only_while_health_remains_public(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "status.sqlite"
            WorkerMonitorStore(database)

            class Handler(PaperHandler):
                auth_db_path = database

                def log_message(self, format, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                env = {
                    "DASHBOARD_AUTH_ENABLED": "true",
                    "DASHBOARD_AUTH_USERNAME": "owner",
                    "DASHBOARD_AUTH_PASSWORD": "secret",
                    "DASHBOARD_BASIC_AUTH_ROLE": "read_only",
                }
                with patch.dict(os.environ, env, clear=True):
                    status, health = _request(base + "/healthz")
                    self.assertEqual(status, 200)
                    self.assertEqual(health["status"], "ok")
                    with self.assertRaises(urllib.error.HTTPError) as unauthenticated:
                        _request(base + "/internal/status.json")
                    self.assertEqual(unauthenticated.exception.code, 401)
                    unauthenticated.exception.close()
                    with self.assertRaises(urllib.error.HTTPError) as forbidden:
                        _request(base + "/internal/status.json", username="owner", password="secret")
                    self.assertEqual(forbidden.exception.code, 403)
                    forbidden.exception.close()
                    os.environ["DASHBOARD_BASIC_AUTH_ROLE"] = "admin"
                    status, internal = _request(base + "/internal/status.json", username="owner", password="secret")
                    self.assertEqual(status, 200)
                    self.assertFalse(internal["public_exposure_allowed"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
