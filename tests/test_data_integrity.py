import json
import datetime
import re
import sys
import unittest
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from fetch_citations import doi_of

RECORDS = json.loads((ROOT / 'data/discoveries.json').read_text())
# Source-corrected dates keep the historical IDs used by existing links.
CORRECTED_DATES = {
    '2024-11-evolvepro': '2025-01-24',
    '2026-10-takotsubo-ecg-deep-learning': '2026-11-08',
    '2026-11-ecg-biomarker-sudden-cardiac-death-deep-learning': '2026-06-24',
    '2026-11-bionic-eye-deep-learning-visual-cortex-stimulation': '2026-08-07',
    '2026-03-ml-screened-w-doped-nifeooh': '2026-01-29',
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

    def test_titles_are_text_not_links(self):
        # A harvested record once carried its announcement URL as the title.
        bad = [d['id'] for d in RECORDS if re.match(r'\s*(https?://|www\.)', d['title'])]
        self.assertEqual(bad, [])

    def test_shared_doi_requires_a_documented_result_split(self):
        by_doi = {}
        for record in RECORDS:
            doi = doi_of(record)
            if doi:
                by_doi.setdefault(doi, []).append(record)
        for doi, records in by_doi.items():
            for first, second in combinations(records, 2):
                with self.subTest(doi=doi, ids=(first['id'], second['id'])):
                    self.assertTrue(any(
                        link['type'] == 'shared evidence' and link['target_id'] == other['id']
                        for record, other in ((first, second), (second, first))
                        for link in record.get('relationships', [])
                    ))

    def test_review_scope_is_self_contained(self):
        for record in RECORDS:
            self.assertNotIn('source_checks', record.get('source_review', {}).get('scope', ''), record['id'])

    def test_archived_duplicate_links_to_the_same_active_publication(self):
        active = {record['id']: record for record in RECORDS}
        archived = {record['id']: record for record in
                    json.loads((ROOT / 'data/archived-discoveries.json').read_text())}
        for duplicate, retained in (
            ('2024-07-study-10-1038-s41467-024-50605-5', '2024-07-transfer-learning-oer-perovskites'),
            ('2025-04-study-10-1038-s41467-025-56818-6', '2025-04-ml-predicts-pancreatic-cancer-drug-synergies'),
            ('2026-01-study-10-1038-s41467-026-68735-3', '2026-03-ml-screened-w-doped-nifeooh'),
        ):
            with self.subTest(duplicate=duplicate):
                self.assertNotIn(duplicate, active)
                self.assertIsNotNone(doi_of(active[retained]))
                self.assertEqual(doi_of(archived[duplicate]), doi_of(active[retained]))
                self.assertIn(('same result', retained),
                              {(link['type'], link['target_id']) for link in archived[duplicate]['relationships']})

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
