from pathlib import Path
import unittest


class TextEncodingTest(unittest.TestCase):
    def test_production_python_sources_do_not_contain_mojibake_markers(self):
        project_root = Path(__file__).resolve().parents[1]
        markers = [
            "绔炲搧",
            "閰嶇疆",
            "浠锋牸",
            "鐘舵",
            "鍙戦",
            "鏃ュ織",
            "妯℃澘",
            "澶辫触",
            "杩愯",
        ]
        offenders = []

        for path in project_root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for marker in markers:
                if marker in text:
                    offenders.append(f"{path.name}: {marker}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
