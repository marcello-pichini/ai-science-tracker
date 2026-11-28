import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VulnerabilityTests(unittest.TestCase):
    """The site's slice of the global vulnerability dataset (scripts/build_vuln_site.py)."""

    @classmethod
    def setUpClass(cls):
        cls.preview = json.loads((ROOT / 'data/vulnerabilities-preview.json').read_text())
        cls.overview = json.loads((ROOT / 'data/vulnerabilities-overview.json').read_text())

    def test_preview_rows_follow_the_preview_rule(self):
        self.assertTrue(self.preview)
        self.assertEqual(len(self.preview), len({r['id'] for r in self.preview}))
        self.assertEqual(len(self.preview), self.overview['totals']['preview'])
        self.assertLess((ROOT / 'data/vulnerabilities-preview.json').stat().st_size, 5_000_000)
        for r in self.preview:
            with self.subTest(id=r['id']):
                self.assertRegex(r['id'], r'^[A-Za-z0-9][A-Za-z0-9:._-]*$')
                self.assertTrue(r.get('priority') == 'act now' or
                                (r.get('score', 0) >= 9 and r.get('published', '') >= self.overview['preview_since']))
                self.assertIn(r['band'], {'critical', 'high', 'medium', 'low', 'none', 'unscored'})
                if 'advisory' in r:
                    self.assertTrue(r['advisory'].startswith(('https://', 'http://')))

    def test_overview_names_every_source_with_its_terms(self):
        t = self.overview['totals']
        self.assertGreater(t['rows'], 400_000)
        self.assertEqual(t['sources'], len(self.overview['sources']))
        notices = ' '.join(s['notice'] for s in self.overview['sources'])
        for required in ('not endorsed or certified by the NVD', 'EPSS scores by FIRST', 'Source: ENISA', 'CC BY 4.0'):
            self.assertIn(required, notices)

    def test_security_page_shows_generated_numbers_sources_and_categories(self):
        page = (ROOT / 'security.html').read_text()
        self.assertIn('The largest and most complete vulnerability dataset in the world', page)
        self.assertIn(f'{self.overview["totals"]["rows"]:,} vulnerabilities joined from', page)
        self.assertIn('data/vulnerabilities-preview.json', page)
        self.assertIn('not endorsed or certified by the NVD', page)
        for c in self.overview['categories']:
            if c['page']:
                self.assertIn(f'profiles/vulnerabilities-{c["slug"]}.html', page)
                self.assertTrue((ROOT / f'profiles/vulnerabilities-{c["slug"]}.html').is_file())
        for name in ('index.html', 'models.html', 'profile.html', 'methodology.html', 'guide.html'):
            self.assertIn('href="security.html"', (ROOT / name).read_text())

    def test_retired_case_pages_redirect_without_indexing(self):
        legacy = json.loads((ROOT / 'data/legacy-security-redirects.json').read_text())
        self.assertEqual(len(legacy), 1780)
        stub = (ROOT / 'profiles/security-2024-big-sleep-sqlite-prerelease.html').read_text()
        self.assertIn('<meta name="robots" content="noindex">', stub)
        self.assertIn('content="0; url=../security.html"', stub)
        sitemap = (ROOT / 'sitemap.xml').read_text()
        self.assertNotIn('profiles/security-', sitemap)
        self.assertIn('profiles/vulnerabilities-', sitemap)
        self.assertFalse((ROOT / 'data/vulnerabilities.json').exists())
        self.assertFalse(re.search(r'api/v1/vulnerabilities/[a-z0-9-]+\.json', (ROOT / 'llms.txt').read_text()))


if __name__ == '__main__':
    unittest.main()
