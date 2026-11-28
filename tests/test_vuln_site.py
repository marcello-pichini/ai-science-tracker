import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import build_vuln_site as vs  # noqa: E402


def row(i, published, score=None, level='low', state='PUBLISHED', kev=None, category=None, classes=()):
    return {'id': i, 'state': state, 'title': None, 'description': 'A flaw. More details here.', 'summary': f'Summary {i}.', 'published': published,
            'severity': {'score': score, 'band': 'critical' if (score or 0) >= 9 else 'high', 'source': 'NVD'} if score else None,
            'priority': {'level': level} if state == 'PUBLISHED' else None, 'kev': kev, 'epss': None,
            'products': [{'product_key': 'acme:server', 'category': category}] if category else [],
            'vuln_class': list(classes), 'exploit_summary': {'maturity': 'none known', 'public_exploit': False},
            'remediation': {'vendor_advisory_urls': ['https://acme.example/sa-1']}}


class SiteExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        build, out = Path(cls.tmp.name) / 'build', Path(cls.tmp.name) / 'data'
        build.mkdir()
        rows = [row('CVE-2026-0001', '2026-06-01T00:00:00Z', 9.8, category='web server', classes=['SQL injection']),
                row('CVE-2025-0002', '2025-06-01T00:00:00Z', 9.8, category='web server'),  # critical, too old
                row('CVE-2020-0003', '2020-01-01T00:00:00Z', 5.0, level='act now', kev={'date_added': '2021-01-01'}),
                row('CVE-2026-0004', '2026-07-01T00:00:00Z', 7.5),  # recent, not critical
                row('CVE-2026-0005', None, None, state='REJECTED'),
                row('GHSA-aaaa-bbbb-cccc', '2026-08-01T00:00:00Z', 9.1)]
        with gzip.open(build / 'vulnerabilities_global.jsonl.gz', 'wt') as f:
            f.writelines(json.dumps(r) + '\n' for r in rows)
        (build / 'build_report.json').write_text(json.dumps({
            'rows': 6, 'cve_states': {'PUBLISHED': 4, 'REJECTED': 1}, 'not_in_cve_list': 0, 'non_cve_rows': 1,
            'products': 1, 'with_kev': 1, 'with_public_exploit': 0, 'malicious_packages': 3}))
        with gzip.open(build / 'categories.json.gz', 'wt') as f:
            json.dump({'web server': [{'product_key': 'acme:server', 'total': 2, 'kev': 0}]}, f)
        cls.overview = vs.export(build, out, '2026-11-27')
        cls.preview = json.loads((out / 'vulnerabilities-preview.json').read_text())

    def test_preview_keeps_exploited_and_recent_critical_only(self):
        self.assertEqual([r['id'] for r in self.preview], ['GHSA-aaaa-bbbb-cccc', 'CVE-2026-0001', 'CVE-2020-0003'])
        self.assertEqual(self.overview['preview_since'], '2025-11-27')

    def test_preview_rows_are_slim_and_linked(self):
        r = next(r for r in self.preview if r['id'] == 'CVE-2026-0001')
        self.assertEqual((r['score'], r['band'], r['category'], r['products']), (9.8, 'critical', 'web server', ['acme:server']))
        self.assertEqual(r['advisory'], 'https://acme.example/sa-1')
        self.assertNotIn('summary', r)
        self.assertEqual(r['description'], 'A flaw.')  # no title: the description's first sentence
        self.assertEqual(vs.links('CVE-2026-0001')['nvd'], 'https://nvd.nist.gov/vuln/detail/CVE-2026-0001')
        self.assertEqual(vs.links('GHSA-aaaa-bbbb-cccc'), {'osv': 'https://osv.dev/vulnerability/GHSA-aaaa-bbbb-cccc'})
        self.assertEqual(vs.links('CNVD-2024-1'), {})
        unscored = next(r for r in self.preview if r['id'] == 'CVE-2020-0003')
        self.assertEqual((unscored['score'], unscored['band'], unscored['kev_added']), (5.0, 'high', '2021-01-01'))

    def test_overview_totals_and_categories(self):
        t = self.overview['totals']
        self.assertEqual((t['rows'], t['cve'], t['non_cve'], t['preview'], t['malicious_packages']), (6, 5, 1, 3, 3))
        self.assertEqual(sum(self.overview['by_year'].values()), 5)  # published rows only
        cat = self.overview['categories'][0]
        self.assertEqual((cat['name'], cat['slug'], cat['total'], cat['page']), ('web server', 'web-server', 2, False))
        self.assertEqual(cat['top_products'][0]['product_key'], 'acme:server')

    def test_every_source_has_licence_and_notice(self):
        self.assertGreaterEqual(len(self.overview['sources']), 20)
        for s in self.overview['sources']:
            self.assertTrue(s['licence'] and s['notice'] and s['url'].startswith('https://'), s)
        self.assertTrue(any('not endorsed or certified by the NVD' in s['notice'] for s in self.overview['sources']))


if __name__ == '__main__':
    unittest.main()
