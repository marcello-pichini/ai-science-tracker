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

    def test_snapshot_date_is_stable_and_data_are_copied_exactly(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)
            hf.build(output, '2026-11-17')
            first = {p.name: p.read_bytes() for p in output.iterdir()}
            hf.build(output, '2026-11-17')
            self.assertEqual(first, {p.name: p.read_bytes() for p in output.iterdir()})
            self.assertIn('on 2026-11-17.', first['README.md'].decode())
            for name in hf.FILES:
                self.assertEqual(first[name], (hf.ROOT / 'data' / name).read_bytes())

    def test_invalid_snapshot_date_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'dataset'
            with self.assertRaises(ValueError):
                hf.build(output, '2026-02-30')
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
