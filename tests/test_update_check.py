import json, os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sys_platform import APP_RELEASE, release_tuple, update_is_newer, fetch_latest_release


class TestUpdateCheck(unittest.TestCase):
    def test_release_format(self):
        self.assertRegex(APP_RELEASE, r"^\d+\.\d+\.\d+(-dev)?$")

    def test_tuple(self):
        self.assertEqual(release_tuple("v0.3.3"), (0, 3, 3))
        self.assertEqual(release_tuple("0.10.1"), (0, 10, 1))
        self.assertEqual(release_tuple("0.4.0-dev"), (0, 4, 0))
        self.assertIsNone(release_tuple("22ze-217"))

    def test_newer(self):
        self.assertTrue(update_is_newer("0.3.4", "0.3.3"))
        self.assertTrue(update_is_newer("0.10.0", "0.9.9"))
        self.assertTrue(update_is_newer("1.0.0", "0.99.99"))
        self.assertFalse(update_is_newer("0.3.3", "0.3.3"))
        self.assertFalse(update_is_newer("0.3.3", "0.4.0-dev"))
        self.assertFalse(update_is_newer("0.4.0", "0.4.0-dev"))
        self.assertFalse(update_is_newer("junk", "0.3.3"))

    def test_fetch_from_local_server(self):
        body = json.dumps({"tag_name": "v0.4.1", "html_url": "http://x/y", "name": "Test"}).encode()

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
        try:
            r = fetch_latest_release("http://127.0.0.1:%d/" % srv.server_port, timeout=3)
        finally:
            srv.shutdown()
        self.assertEqual(r["version"], "0.4.1")
        self.assertEqual(r["url"], "http://x/y")

    def test_fetch_failure_raises(self):
        with self.assertRaises(Exception):
            fetch_latest_release("http://127.0.0.1:9/", timeout=1)


if __name__ == "__main__":
    unittest.main()
