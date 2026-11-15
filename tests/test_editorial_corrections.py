"""Admission and version-date regressions for explicitly reviewed catalog events."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EditorialCorrectionTests(unittest.TestCase):
    def test_prospective_hypotheses_and_release_events_keep_history_outside_counts(self):
        active = {r['id'] for r in json.loads((ROOT / 'data/discoveries.json').read_text())}
        archived = {r['id']: r for r in json.loads((ROOT / 'data/archived-discoveries.json').read_text())}
        for rid in ('2026-05-co-scientist-sla','2026-05-co-scientist-interruttori-molecolari',
                    '2025-05-omol25-uma','2025-04-dolphingemma','2025-08-perch-bioacustica',
                    '2026-11-physics-based-differentiable-imaging-detects-51-eridani-b-in-a-jwst-band-where-standard-processing-did-not'):
            self.assertNotIn(rid, active)
            self.assertIn(rid, archived)
            self.assertTrue(archived[rid]['summary'].startswith('Archived from discovery counts:'))

    def test_kls_result_uses_resolving_version_date_and_confirmation_source(self):
        rows = json.loads((ROOT / 'data/discoveries.json').read_text())
        row = next(r for r in rows if r['id'] == '2026-10-ai-assisted-proof-establishes-a-dimension-independent-kls-isoperimetric-bound')
        self.assertEqual(row['publication_date'], '2026-10-04')
        self.assertTrue(any('microsoft.com/en-us/research/blog/' in u for u in row['evidence']['evidence_urls']))
        self.assertIn('1 October', row['summary'])
        self.assertIn('4 October', row['summary'])

    def test_cohort_collection_is_distinct_from_prospective_model_evaluation(self):
        rows = {r['id']:r for r in json.loads((ROOT / 'data/discoveries.json').read_text())}
        for rid in ('2026-04-redmod-pancreas','2023-01-sybil-polmone',
                    '2026-11-lightgbm-feature-selection-identifies-a-four-protein-panel-associated-with-incident-chronic-kidney-disease',
                    '2026-02-ai-derived-histology-biomarker-stratifies-first-line-chemotherapy-outcomes-in-advanced-pancreatic-cancer'):
            self.assertEqual(rows[rid]['evidence']['test_type'], 'retrospective or benchmark')
            self.assertEqual(rows[rid]['relevance']['validation'], 2)
        candidate = rows['2022-10-prospective-machine-learning-screen-identifies-six-previously-unreported-oatp1b1-inhibitors']
        self.assertEqual(candidate['evidence']['test_type'], 'direct test')
        self.assertEqual(candidate['relevance']['validation'], 3)

    def test_institution_names_remain_complete_in_data(self):
        rows = json.loads((ROOT / 'data/discoveries.json').read_text())
        xunzi = next(r for r in rows if r['id'] == '2026-08-xunzi-prioritizes-chk2-as-a-parkinsons-disease-mechanism-and-therapeutic-target')
        self.assertEqual(xunzi['organization'].split(';')[0], 'Huazhong University of Science and Technology')
        campuses = {r['organization'].split(';')[0] for r in rows if r['organization'].startswith('University of California,')}
        self.assertIn('University of California, Berkeley', campuses)
        self.assertIn('University of California, Davis', campuses)
