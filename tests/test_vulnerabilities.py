import datetime
import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


class VulnerabilityTests(unittest.TestCase):
    def test_individual_disclosures_preserve_ai_and_remediation_evidence(self):
        path = ROOT / 'data/vulnerabilities.json'
        self.assertTrue(path.is_file(), 'AI vulnerability dataset is not implemented yet')
        records = json.loads(path.read_text())
        self.assertTrue(records)
        self.assertEqual(len(records), len({r['id'] for r in records}))
        seen = set()
        keys = {'id', 'title', 'product', 'ai_system', 'organization', 'summary', 'ai_role',
                'disclosure_date', 'ai_attribution_date', 'classification', 'classification_note',
                'cves', 'source_url', 'ai_source_url', 'remediation', 'remediation_note',
                'advisory_url', 'checked_date'}
        for r in records:
            with self.subTest(case=r['id']):
                self.assertEqual(set(r) - {'cvss', 'impacts'}, keys)
                self.assertIn(r['classification'], {'undisclosed', 'pre-release', 'disclosure'})
                self.assertIn(r['remediation'], {'fix documented', 'not established'})
                for field in ('source_url', 'ai_source_url', 'advisory_url'):
                    self.assertEqual(urlsplit(r[field]).scheme, 'https')
                for field in ('disclosure_date', 'ai_attribution_date', 'checked_date'):
                    if field == 'ai_attribution_date' and r[field] is None:
                        continue
                    datetime.date.fromisoformat(r[field])
                self.assertGreaterEqual(r['checked_date'], r['disclosure_date'])
                for field in ('ai_role', 'classification_note', 'remediation_note'):
                    self.assertTrue(r[field].strip())
                for cve in r['cves']:
                    self.assertRegex(cve, r'^CVE-\d{4}-\d{4,}$')
                    self.assertNotIn(cve, seen)
                    seen.add(cve)
        by_id = {r['id']: r for r in records}
        # Previously unknown pre-release bugs must not become production zero-days.
        self.assertEqual(by_id['2024-big-sleep-sqlite-prerelease']['classification'], 'pre-release')
        self.assertEqual(by_id['2024-big-sleep-sqlite-prerelease']['cves'], [])

    def test_security_page_is_part_of_the_site(self):
        page = ROOT / 'security.html'
        self.assertTrue(page.is_file(), 'Security tracker page is not implemented yet')
        self.assertIn('data/vulnerabilities.json', page.read_text())
        for name in ('index.html', 'models.html', 'profile.html', 'methodology.html', 'guide.html'):
            self.assertIn('href="security.html"', (ROOT / name).read_text())
