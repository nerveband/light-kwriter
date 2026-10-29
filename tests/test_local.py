import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer


class LocalAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["EINK_DATA_DIR"] = cls.temp.name
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("local_app", root / "server.py")
        cls.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.app)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), cls.app.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(
            self.base + "/api/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_save_survives_a_new_request_and_reaches_disk(self):
        data = {"draft": "Written offline", "presets": [{"task": "Read"}]}
        self.assertEqual(self.request("save", data)[0], 200)
        self.assertEqual(self.request("data")[1], data)
        saved = json.loads((Path(self.temp.name) / "data.json").read_text())
        self.assertEqual(saved, data)

    def test_another_site_cannot_write_or_use_its_own_hostname(self):
        self.assertEqual(self.request("save", {}, {"Origin": "https://other.example"})[0], 403)
        self.assertEqual(self.request("state", headers={"Host": "other.example"})[0], 403)

    def test_invalid_screen_and_transport_are_rejected(self):
        self.assertEqual(self.request("frame", {"rotation": 99, "image": ""})[0], 400)
        self.assertEqual(self.request("frame", {"rotation": 3, "image": "broken"})[0], 400)
        self.assertEqual(self.request("connect", {"enabled": True, "transport": "other"})[0], 400)
        self.assertFalse(self.app.kindle.enabled)


if __name__ == "__main__":
    unittest.main()
