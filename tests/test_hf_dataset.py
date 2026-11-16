import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_hf_dataset as hf


class HfDatasetTest(unittest.TestCase):
    def test_size_category(self):
        self.assertEqual(hf.size_category(999), "n<1K")
        self.assertEqual(hf.size_category(1000), "1K<n<10K")

    def test_card_has_no_placeholders(self):
        with tempfile.TemporaryDirectory() as d:
            counts = hf.build(Path(d))
            card = (Path(d) / "README.md").read_text()
        for key in ("{discoveries}", "{vulnerabilities}", "{size}", "{date}"):
            self.assertNotIn(key, card)
        self.assertIn(f"| {counts['discoveries']} |", card)


if __name__ == "__main__":
    unittest.main()
