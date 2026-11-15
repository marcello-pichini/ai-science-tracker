import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MethodologyCoverageTests(unittest.TestCase):
    def run_metrics(self, entries):
        page = (ROOT / 'methodology.html').read_text()
        script = re.search(r'<script id="coverage-metrics">(.*?)</script>', page, re.S)
        self.assertIsNotNone(script, 'Coverage metrics are not implemented yet')
        result = subprocess.run(
            ['node', '-e', script[1] + '\nprocess.stdout.write(JSON.stringify(coverageByYear(JSON.parse(require("fs").readFileSync(0, "utf8")))));'],
            input=json.dumps(entries), text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_years_count_every_entry_once_and_do_not_infer_annotations_from_sources(self):
        entries = [
            {'publication_date': '2026-02-02', 'source_type': 'paper'},
            {'publication_date': '2025-01-01', 'source_type': 'blog', 'evidence': {'publication_status': 'Preprint'}},
            {'publication_date': '2025-03-01', 'source_type': 'paper'},
            {'publication_date': '2025-03-01', 'source_type': 'press release', 'evidence': {'publication_status': 'Not reported'}},
            {'publication_date': '2025-05-01', 'source_type': 'other'},
        ]
        self.assertEqual(self.run_metrics(entries), [
            {'year': '2025', 'total': 4, 'annotated': 2, 'missing': 2, 'sources': {'paper': 1, 'blog': 1, 'press release': 1, 'other': 1}},
            {'year': '2026', 'total': 1, 'annotated': 0, 'missing': 1, 'sources': {'paper': 1, 'blog': 0, 'press release': 0, 'other': 0}},
        ])

    def test_empty_catalog_has_no_invented_years_or_denominators(self):
        self.assertEqual(self.run_metrics([]), [])

    def test_live_catalog_annual_denominators_reconcile(self):
        entries = json.loads((ROOT / 'data/discoveries.json').read_text())
        rows = self.run_metrics(entries)
        self.assertEqual(sum(row['total'] for row in rows), len(entries))
        self.assertEqual(sum(row['annotated'] for row in rows), sum('evidence' in entry for entry in entries))
        for row in rows:
            self.assertEqual(row['annotated'] + row['missing'], row['total'])
            self.assertEqual(sum(row['sources'].values()), row['total'])
