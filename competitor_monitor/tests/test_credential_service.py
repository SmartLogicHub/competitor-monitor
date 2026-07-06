import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from credential_service import (
    AccountCredentials,
    BICredentials,
    load_bi_credentials,
    load_taobao_credentials,
    save_account_credentials,
    save_bi_credentials,
)


class CredentialServiceTest(unittest.TestCase):
    def test_loads_bi_credentials_from_environment_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "bi_credentials.json"
            save_bi_credentials(credentials_path, "file-user", "file-pass")

            with patch.dict(os.environ, {"BI_USER": "env-user", "BI_PASSWORD": "env-pass"}):
                credentials = load_bi_credentials({"bi_credentials_path": str(credentials_path)})

        self.assertEqual(credentials, BICredentials(username="env-user", password="env-pass"))

    def test_loads_bi_credentials_from_local_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "bi_credentials.json"
            save_bi_credentials(credentials_path, "file-user", "file-pass")

            with patch.dict(os.environ, {}, clear=True):
                credentials = load_bi_credentials({"bi_credentials_path": str(credentials_path)})

        self.assertEqual(credentials, BICredentials(username="file-user", password="file-pass"))

    def test_loads_bi_credentials_from_utf8_bom_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "bi_credentials.json"
            credentials_path.write_text('{"username":"file-user","password":"file-pass"}', encoding="utf-8-sig")

            with patch.dict(os.environ, {}, clear=True):
                credentials = load_bi_credentials({"bi_credentials_path": str(credentials_path)})

        self.assertEqual(credentials, BICredentials(username="file-user", password="file-pass"))

    def test_returns_none_when_no_credentials_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "missing.json"

            with patch.dict(os.environ, {}, clear=True):
                credentials = load_bi_credentials({"bi_credentials_path": str(credentials_path)})

        self.assertIsNone(credentials)

    def test_loads_taobao_credentials_from_environment_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "taobao_credentials.json"
            save_account_credentials(credentials_path, "file-user", "file-pass")

            with patch.dict(os.environ, {"TAOBAO_USER": "env-user", "TAOBAO_PASSWORD": "env-pass"}):
                credentials = load_taobao_credentials({"taobao_credentials_path": str(credentials_path)})

        self.assertEqual(credentials, AccountCredentials(username="env-user", password="env-pass"))

    def test_loads_taobao_credentials_from_local_secret_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "taobao_credentials.json"
            save_account_credentials(credentials_path, "file-user", "file-pass")

            with patch.dict(os.environ, {}, clear=True):
                credentials = load_taobao_credentials({"taobao_credentials_path": str(credentials_path)})

        self.assertEqual(credentials, AccountCredentials(username="file-user", password="file-pass"))


if __name__ == "__main__":
    unittest.main()
