"""Monitoring catches content drift even when counts and HTTP status look healthy."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publication_monitor', ROOT / 'scripts/check_publication.py')
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)
LINK_SPEC = importlib.util.spec_from_file_location('source_link_monitor', ROOT / 'scripts/check_links.py')
links = importlib.util.module_from_spec(LINK_SPEC)
LINK_SPEC.loader.exec_module(links)


class PublicationMonitorTest(unittest.TestCase):
    def test_same_count_different_record_is_a_failure(self):
        self.assertFalse(monitor.same_data(b'[{"id":"a"}]', b'[{"id":"b"}]', 'records.json'))
        self.assertTrue(monitor.same_data(b'{"a":1,"b":2}', b'{"b":2,"a":1}', 'records.json'))

    def test_live_parity_covers_assets_site_and_hf_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for directory in ('data', 'api/v1', 'assets'):
                (root / directory).mkdir(parents=True)
            for name in monitor.DATA:
                (root / 'data' / name).write_text('[{"id":"sample"}]')
            for name in monitor.HF_FILES:
                if not name.endswith('.json'):
                    (root / 'data' / name).write_text('id\nsample\n')
            (root / 'api/v1/index.json').write_text('{}')
            (root / 'assets/app.js').write_text('current-version')

            def fetch(url):
                path = urlsplit(url).path.lstrip('/')
                if path.endswith('.html'):
                    return b'<title>Catalog</title><h1>Catalog</h1><script src="/assets/app.js"></script>'
                if urlsplit(url).netloc == 'hf.test':
                    return (root / 'data' / Path(path).name).read_bytes()
                return (root / path).read_bytes()

            release = {'tagName': 'v2026.11.18', 'publishedAt': '2026-11-18T00:00:00Z'}
            def complete_fetch(url):
                if 'doi.org' in url:
                    return b'<p>Version v2026.11.18</p>'
                return fetch(url)
            good = monitor.check(root, 'https://site.test/', 'https://hf.test/', release, complete_fetch)
            self.assertTrue(all(r['status'] == 'pass' for r in good))

            def stale_fetch(url):
                if '/assets/app.js' in url:
                    return b'old-version'
                if urlsplit(url).netloc == 'hf.test' and 'discoveries.json' in url:
                    return b'[{"id":"different"}]'
                return complete_fetch(url)
            bad = monitor.check(root, 'https://site.test/', 'https://hf.test/', release, stale_fetch)
            failed = {r['check'] for r in bad if r['status'] == 'fail'}
            self.assertEqual(failed, {'asset/assets/app.js', 'hugging-face/discoveries.json'})

    def test_zenodo_grace_period_and_missing_archive(self):
        release = {'tagName': 'v2026.11.18', 'publishedAt': '2026-11-18T10:00:00Z'}
        old = b'<script>Version v2026.11.18</script><p>Version v2026.11.17</p>'
        self.assertEqual(monitor.check_zenodo(old, release, dt.datetime(2026, 11, 18, 11, tzinfo=dt.timezone.utc))[0], 'pending')
        self.assertEqual(monitor.check_zenodo(old, release, dt.datetime(2026, 11, 18, 13, tzinfo=dt.timezone.utc))[0], 'fail')
        self.assertEqual(monitor.check_zenodo(b'<p>Version v2026.11.18</p>', release)[0], 'pass')


class LinkMonitorTest(unittest.TestCase):
    def test_missing_links_require_confirmation(self):
        self.assertEqual(links.inspect('https://example.test', lambda _: '404')['status'], 'gone')
        replies = iter(['404', '200'])
        self.assertEqual(links.inspect('https://example.test', lambda _: next(replies))['status'], 'uncertain')

    def test_access_blocks_and_transient_failures_are_inconclusive(self):
        for code in ('403', '429', '500', '000', '301'):
            with self.subTest(code=code):
                self.assertEqual(links.inspect('https://example.test', lambda _: code)['status'], 'uncertain')
        self.assertEqual(links.inspect('https://example.test', lambda _: '200')['status'], 'ok')

    def test_non_web_links_never_reach_curl(self):
        with patch.object(links.subprocess, 'run') as run:
            self.assertEqual(links.status('file:///private/example'), 'invalid')
            self.assertEqual(links.status('javascript:alert(1)'), 'invalid')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
