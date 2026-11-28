import datetime
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('collect_metrics', ROOT / 'scripts/collect_metrics.py')
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)

ABSTRACT = 'Abstract read from Europe PMC metadata for this DOI. Publisher full text not accessed.'
EXCERPTS = 'Abstract and Europe PMC full-text Methods/Results excerpts read. Publisher version not otherwise accessed.'


class CollectMetricsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / 'data').mkdir()
        records = [
            {'verification_status': 'verified', 'source_review': {'scope': ABSTRACT}},
            {'verification_status': 'verified', 'source_review': {'scope': EXCERPTS}},
            {'verification_status': 'verified', 'source_review': {'scope': 'Primary Methods and Results reviewed.'}},
            {'verification_status': 'needs verification', 'source_review': {'scope': ABSTRACT}},
        ]
        (self.root / 'data/discoveries.json').write_text(json.dumps(records))
        (self.root / 'data/vulnerabilities-overview.json').write_text(json.dumps({'totals': {'rows': 2}}))
        self.today = datetime.date(2026, 11, 27)

    def fake(self, url, token=None):
        if 'huggingface' in url:
            return {'downloads': 658, 'downloadsAllTime': 700, 'likes': 1}
        if 'zenodo' in url:
            return {'stats': {'downloads': 149, 'unique_downloads': 147, 'views': 70, 'unique_views': 59,
                              'version_downloads': 0}}
        if url.endswith('/traffic/views'):
            self.assertEqual(token, 'secret')
            return {'count': 30, 'uniques': 12}
        return {'stargazers_count': 5, 'open_issues_count': 2}

    def test_row_combines_all_sources(self):
        row = metrics.build_row(self.root, self.fake, 'secret', self.today, io.StringIO())
        self.assertEqual(list(row), metrics.COLUMNS)
        self.assertEqual(row['date'], '2026-11-27')
        self.assertEqual((row['hf_downloads_30d'], row['zenodo_downloads'], row['github_stars']), (658, 149, 5))
        self.assertEqual((row['github_views_14d'], row['github_uniques_14d']), (30, 12))
        self.assertEqual((row['discoveries'], row['discoveries_verified'], row['discoveries_needs_verification']), (4, 3, 1))
        self.assertEqual((row['verified_abstract_only'], row['vulnerabilities']), (1, 2))

    def test_failing_sources_leave_others_intact(self):
        def flaky(url, token=None):
            if 'zenodo' in url or 'huggingface' in url:
                raise OSError('down')
            return self.fake(url, token)
        log = io.StringIO()
        row = metrics.build_row(self.root, flaky, None, self.today, log)
        self.assertEqual((row['hf_downloads_30d'], row['zenodo_views'], row['github_views_14d']), ('', '', ''))
        self.assertEqual((row['github_stars'], row['discoveries']), (5, 4))
        self.assertIn('zenodo skipped', log.getvalue())
        self.assertIn('github-traffic skipped', log.getvalue())


if __name__ == '__main__':
    unittest.main()
