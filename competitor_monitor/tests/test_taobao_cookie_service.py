import importlib
import json
import tempfile
import unittest
from pathlib import Path


class TaobaoCookieServiceTest(unittest.TestCase):
    def load_service(self):
        try:
            return importlib.import_module("taobao_cookie_service")
        except ModuleNotFoundError:
            self.fail("taobao_cookie_service module is missing")

    def test_accepts_playwright_storage_state_and_filters_other_domains(self):
        service = self.load_service()
        content = json.dumps(
            {
                "cookies": [
                    {"name": "tb", "value": "secret", "domain": ".taobao.com", "path": "/"},
                    {"name": "tm", "value": "secret2", "domain": "detail.tmall.com", "path": "/"},
                    {"name": "other", "value": "no", "domain": ".example.com", "path": "/"},
                ],
                "origins": [{"origin": "https://example.com", "localStorage": []}],
            }
        ).encode("utf-8")

        state = service.normalize_taobao_cookie_export(content)

        self.assertEqual([cookie["name"] for cookie in state["cookies"]], ["tb", "tm"])
        self.assertEqual(state["origins"], [])

    def test_accepts_cookie_editor_array_and_normalizes_fields(self):
        service = self.load_service()
        content = json.dumps(
            [
                {
                    "name": "token",
                    "value": "secret",
                    "domain": ".tmall.com",
                    "path": "/",
                    "expirationDate": 1999999999.0,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "no_restriction",
                }
            ]
        ).encode("utf-8")

        state = service.normalize_taobao_cookie_export(content)

        self.assertEqual(state["cookies"][0]["expires"], 1999999999.0)
        self.assertEqual(state["cookies"][0]["sameSite"], "None")
        self.assertTrue(state["cookies"][0]["httpOnly"])

    def test_rejects_invalid_json_and_exports_without_taobao_cookies(self):
        service = self.load_service()

        with self.assertRaises(service.CookieImportError):
            service.normalize_taobao_cookie_export(b"not-json")
        with self.assertRaises(service.CookieImportError):
            service.normalize_taobao_cookie_export(
                b'[{"name":"x","value":"y","domain":"example.com"}]'
            )

    def test_import_writes_storage_state_atomically(self):
        service = self.load_service()
        content = b'[{"name":"token","value":"secret","domain":".taobao.com","path":"/"}]'

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "profile" / "storage_state.json"
            count = service.import_taobao_cookie_export(content, target)
            saved = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(count, 1)
        self.assertEqual(saved["cookies"][0]["value"], "secret")


if __name__ == "__main__":
    unittest.main()
