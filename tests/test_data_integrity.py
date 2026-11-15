import json
import datetime
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = json.loads((ROOT / 'data/discoveries.json').read_text())
# Source-corrected dates keep the historical IDs used by existing links.
CORRECTED_DATES = {
    '2024-11-evolvepro': '2025-01-24',
    '2026-10-takotsubo-ecg-deep-learning': '2026-11-08',
    '2026-11-ecg-biomarker-sudden-cardiac-death-deep-learning': '2026-06-24',
    '2026-11-bionic-eye-deep-learning-visual-cortex-stimulation': '2026-08-07',
}


class DataIntegrityTests(unittest.TestCase):
    """Invariants that hold today; a future legitimate exception needs an explicit allowlist and a reason."""

    def test_no_duplicate_source_or_title(self):
        for key, norm in (('source_url', lambda v: v.rstrip('/')), ('title', str.lower)):
            seen = {}
            for r in RECORDS:
                value = norm(r[key])
                self.assertNotIn(value, seen, f'{key} of {r["id"]} duplicates {seen.get(value)}')
                seen[value] = r['id']

    def test_dates_and_ids_are_coherent(self):
        for r in RECORDS:
            self.assertGreaterEqual(r['publication_date'], '2020-01-01', r['id'])
            self.assertLessEqual(r['publication_date'], datetime.date.today().isoformat(), r['id'])
            self.assertGreaterEqual(r['added_date'], r['publication_date'], r['id'])
            if r['id'] in CORRECTED_DATES:
                self.assertEqual(r['publication_date'], CORRECTED_DATES[r['id']], r['id'])
            else:
                self.assertTrue(r['id'].startswith(r['publication_date'][:7]), r['id'])

    def test_links_are_https_and_paper_differs_from_source(self):
        for r in RECORDS:
            self.assertTrue(r['source_url'].startswith('https://'), r['id'])
            if r['paper_url']:
                self.assertTrue(r['paper_url'].startswith('https://'), r['id'])
                self.assertNotEqual(r['paper_url'].rstrip('/'), r['source_url'].rstrip('/'), r['id'])


if __name__ == '__main__':
    unittest.main()
