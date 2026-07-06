import tempfile
import unittest
from pathlib import Path

from config_service import _load_simple_yaml


class ConfigServiceTest(unittest.TestCase):
    def test_simple_yaml_loader_handles_nested_activity_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text(
                """
excel_path: "竞品监控.xlsx"
force_overwrite: false
retry_count: 1
activity_mapping:
  国补:
    - 政府补贴
    - 国补
keep_original_activities:
  - 618开门红
""".strip(),
                encoding="utf-8",
            )

            config = _load_simple_yaml(path)

            self.assertEqual(config["excel_path"], "竞品监控.xlsx")
            self.assertFalse(config["force_overwrite"])
            self.assertEqual(config["retry_count"], 1)
            self.assertEqual(config["activity_mapping"]["国补"], ["政府补贴", "国补"])
            self.assertEqual(config["keep_original_activities"], ["618开门红"])


if __name__ == "__main__":
    unittest.main()
