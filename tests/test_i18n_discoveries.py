"""Idempotent extract and merge for discovery summary translations."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import i18n_discoveries as i18n  # noqa: E402


ENGLISH = [
    {"id": "a", "summary": "A model reported an association in 12 patients, AUROC 0.91."},
    {"id": "b", "summary": "A model reported an association in 12 patients, AUROC 0.91."},
    {"id": "c", "summary": "Short exploratory note about a benchmark."},
    {"id": "d", "summary": "AlphaFold2 kept this proper name and the figure 3.5%."},
]


class DiscoveryTranslationHelperTests(unittest.TestCase):
    def test_extract_skips_present_and_duplicate_strings(self):
        overlay = {"c": {"summary": "Nota esplorativa breve su un benchmark."}}
        items = i18n.missing_items(ENGLISH, overlay, ("summary",))
        self.assertEqual([item["id"] for item in items], ["d", "a"])

    def test_merge_is_idempotent_and_propagates_duplicates(self):
        overlay = {"d": {"summary": "AlphaFold2 ha conservato questo nome proprio e la cifra 3.5%."}}
        translated = [{
            "id": "a",
            "field": "summary",
            "text": "Un modello ha riportato un’associazione in 12 pazienti, AUROC 0.91.",
        }]
        first = i18n.merge_translations(overlay, ENGLISH, translated)
        self.assertEqual(first["merged"], 1)
        self.assertEqual(first["propagated"], 1)
        self.assertEqual(overlay["b"]["summary"], overlay["a"]["summary"])
        self.assertTrue(overlay["d"]["summary"].startswith("AlphaFold2 ha conservato"))
        snapshot = json.dumps(overlay, ensure_ascii=False, sort_keys=True)
        second = i18n.merge_translations(overlay, ENGLISH, translated)
        self.assertEqual(second["merged"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(json.dumps(overlay, ensure_ascii=False, sort_keys=True), snapshot)

    def test_plain_acronym_ai_may_become_the_locale_abbreviation(self):
        problems = i18n.translation_problems(
            "AI measures exophthalmos from orbital CT images.",
            "L’IA misura l’esoftalmo da immagini TC orbitarie.",
        )
        self.assertEqual(problems, [])

    def test_merge_rejects_dropped_numbers_and_unknown_ids(self):
        overlay = {}
        translated = [
            {"id": "a", "field": "summary", "text": "Un modello ha riportato un’associazione nei pazienti."},
            {"id": "missing", "field": "summary", "text": "Testo con 12 e 0.91."},
        ]
        result = i18n.merge_translations(overlay, ENGLISH, translated)
        self.assertEqual(result["merged"], 0)
        self.assertEqual(overlay, {})
        reasons = {item["id"]: item["reason"] for item in result["problems"]}
        self.assertIn("missing-token:12", reasons["a"])
        self.assertEqual(reasons["missing"], "unknown-id")

    def test_merge_does_not_apply_a_stale_source(self):
        overlay = {}
        translated = [{
            "id": "c",
            "field": "summary",
            "text": "Nota esplorativa breve su un benchmark.",
        }]
        result = i18n.merge_translations(
            overlay, ENGLISH, translated, against={"c": "An older English summary."})
        self.assertEqual(result["stale"], 1)
        self.assertNotIn("c", overlay)

    def test_cli_extract_merge_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "i18n" / "discoveries").mkdir(parents=True)
            (root / "data" / "discoveries.json").write_text(json.dumps(ENGLISH), encoding="utf-8")
            (root / "i18n" / "discoveries" / "it.json").write_text("{}\n", encoding="utf-8")
            out = root / "batches"
            script = ROOT / "scripts" / "i18n_discoveries.py"
            extract = subprocess.run(
                [sys.executable, str(script), "--root", str(root), "extract",
                 "--lang", "it", "--out", str(out), "--batch-size", "2"],
                text=True, capture_output=True, check=False)
            self.assertEqual(extract.returncode, 0, extract.stderr)
            self.assertIn("3 missing strings", extract.stdout)
            done = out / "done-001.jsonl"
            done.write_text(
                '{"id":"d","summary":"AlphaFold2 ha conservato questo nome proprio e la cifra 3.5%."}\n'
                '{"c":"Nota esplorativa breve su un benchmark."}\n',
                encoding="utf-8")
            verify = subprocess.run(
                [sys.executable, str(script), "--root", str(root), "verify", "--lang", "it",
                 "--source", str(out / "batch-001.jsonl"), "--translated", str(done)],
                text=True, capture_output=True, check=False)
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            merge = subprocess.run(
                [sys.executable, str(script), "--root", str(root), "merge", "--lang", "it",
                 "--against", str(out / "batch-001.jsonl"), str(done)],
                text=True, capture_output=True, check=False)
            self.assertEqual(merge.returncode, 0, merge.stderr)
            self.assertIn("merged 2", merge.stdout)
            overlay = json.loads((root / "i18n" / "discoveries" / "it.json").read_text(encoding="utf-8"))
            self.assertIn("AlphaFold2", overlay["d"]["summary"])
            self.assertNotIn("a", overlay)
            again = subprocess.run(
                [sys.executable, str(script), "--root", str(root), "merge", "--lang", "it", str(done)],
                text=True, capture_output=True, check=False)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("merged 0", again.stdout)
            self.assertEqual(
                (root / "i18n" / "discoveries" / "it.json").read_text(encoding="utf-8"),
                json.dumps(overlay, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
