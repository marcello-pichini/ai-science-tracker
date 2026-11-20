"""Monitoring catches content drift even when counts and HTTP status look healthy."""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publication_monitor', ROOT / 'scripts/check_publication.py')
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)
LINK_SPEC = importlib.util.spec_from_file_location('source_link_monitor', ROOT / 'scripts/check_links.py')
links = importlib.util.module_from_spec(LINK_SPEC)
LINK_SPEC.loader.exec_module(links)


def sample_page(path):
    return (f'<link rel="canonical" href="https://site.test/{path}">'
            '<title>Catalog</title><h1>Catalog</h1><script src="/assets/app.js"></script>').encode()


def write_sample_pages(root):
    for path in (*monitor.PAGES, 'share/sample.html'):
        page = root / path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(sample_page(path))


class PublicationMonitorTest(unittest.TestCase):
    def test_default_fetch_returns_body_and_inspection_metadata(self):
        response = MagicMock()
        response.read.return_value = b'catalog'
        response.status = 200
        response.geturl.return_value = 'https://site.test/final'
        response.headers.get_all.return_value = ['index, follow']
        context = MagicMock()
        context.__enter__.return_value = response
        with patch.object(monitor, 'urlopen', return_value=context):
            self.assertEqual(monitor.fetch('https://site.test/', attempts=1), b'catalog')
            self.assertEqual(monitor.fetch('https://site.test/', attempts=1, inspect=True),
                             (b'catalog', 200, 'https://site.test/final', ['index, follow']))
            response.read.assert_called_with(monitor.MAX_BYTES + 1)
            with patch.object(monitor, 'MAX_BYTES', 3):
                for inspect in (False, True):
                    with self.subTest(inspect=inspect), self.assertRaisesRegex(ValueError, 'size limit'):
                        monitor.fetch('https://site.test/', attempts=1, inspect=inspect)

    def test_page_identity_rejects_soft_404_and_robots_conflicts(self):
        url = 'https://site.test/dataset.html'
        expected, error = monitor.Page(), monitor.Page()
        expected.feed(sample_page('dataset.html').decode())
        error.feed('<title>Page not found</title><h1>Page not found</h1>')
        self.assertEqual(monitor.check_page(expected, error, url, url, 200, [])[0], 'fail')
        self.assertEqual(monitor.check_page(expected, expected, url, url, 200, ['noindex'])[0], 'fail')
        self.assertEqual(monitor.check_page(expected, expected, url, url + '?other=1', 200, [])[0], 'fail')
        self.assertEqual(monitor.check_page(expected, expected, url, url, 200, [])[0], 'pass')


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
            (root / 'data/benchmarks').mkdir()
            benchmark = root / 'data/benchmarks/sample.json'
            benchmark.write_text('{"score": 1}')
            registry = {'schema_version': 1, 'sources': [{'path': 'data/benchmarks/sample.json',
                        'sha256': hashlib.sha256(benchmark.read_bytes()).hexdigest()}]}
            registry_path = root / 'data/benchmarks/index.json'
            registry_path.write_text(json.dumps(registry))

            write_sample_pages(root)

            def fetch(url):
                path = urlsplit(url).path.lstrip('/')
                if path.endswith('.html'):
                    return sample_page(path)
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
                if '/data/benchmarks/sample.json' in url:
                    return b'{"score": 2}'
                if '/assets/app.js' in url:
                    return b'old-version'
                if urlsplit(url).netloc == 'hf.test' and 'discoveries.json' in url:
                    return b'[{"id":"different"}]'
                return complete_fetch(url)
            bad = monitor.check(root, 'https://site.test/', 'https://hf.test/', release, stale_fetch)
            failed = {r['check'] for r in bad if r['status'] == 'fail'}
            self.assertEqual(failed, {'asset/assets/app.js', 'hugging-face/discoveries.json', 'site/data/benchmarks/sample.json'})
            registry['sources'][0]['path'] = '../private.json'
            registry_path.write_text(json.dumps(registry))
            with self.assertRaisesRegex(ValueError, 'Unsafe component path'):
                monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=complete_fetch)
            registry_path.write_text('{invalid')
            with self.assertRaises(ValueError):
                monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=complete_fetch)
            registry_path.unlink()
            with self.assertRaisesRegex(ValueError, 'Benchmark registry missing'):
                monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=complete_fetch)

    def test_component_manifest_detects_exact_byte_drift_and_new_components(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for directory in ('data', 'api/v1'):
                (root / directory).mkdir(parents=True)
            for name in set(monitor.DATA + monitor.HF_FILES + ('citations.json',)):
                (root / 'data' / name).write_text('[{"id":"sample"}]' if name.endswith('.json') else 'id\nsample\n')
            (root / 'api/v1/index.json').write_text('{}')
            raw = (root / 'data/citations.json').read_bytes()
            (root / 'api/v1/manifest.json').write_text(json.dumps({'components': {'citations': {'path': 'data/citations.json', 'sha256': hashlib.sha256(raw).hexdigest()}}}))
            (root / 'assets').mkdir()
            (root / 'assets/app.js').write_text('current-version')
            write_sample_pages(root)
            def fetch(url):
                if 'doi.org' in url:
                    return b'<p>Version v2026.11.18</p>'
                path = urlsplit(url).path.lstrip('/')
                if path.endswith('.html'):
                    return sample_page(path)
                if urlsplit(url).netloc == 'hf.test':
                    return (root / 'data' / Path(path).name).read_bytes()
                if path in ('data/citations.json', 'api/v1/manifest.json'):
                    return (root / path).read_bytes() + b'\n'
                return (root / path).read_bytes()
            results = monitor.check(root, 'https://site.test/', 'https://hf.test/', {'tagName':'v2026.11.18', 'publishedAt':'2026-11-18T00:00:00Z'}, fetcher=fetch, allow_legacy_benchmarks=True)
            failed = {r['check']: r['detail'] for r in results if r['status'] == 'fail'}
            self.assertEqual(set(failed), {'site/data/citations.json', 'site/api/v1/manifest.json'})
            self.assertIn('SHA-256', failed['site/data/citations.json'])

    def test_deployment_freshness_current_pending_then_stale(self):
        metadata = {'expected_sha': 'a' * 40, 'deployed_sha': 'b' * 40,
                    'expected_updated_at': '2026-11-18T10:00:00Z'}
        for hour, expected in ((11, 'pending'), (12, 'fail'), (13, 'fail')):
            with self.subTest(hour=hour):
                self.assertEqual(monitor.check_freshness(metadata, dt.datetime(2026, 11, 18, hour,
                                 tzinfo=dt.timezone.utc))[0], expected)
        metadata['deployed_sha'] = metadata['expected_sha']
        self.assertEqual(monitor.check_freshness(metadata, dt.datetime(2026, 11, 18, 13,
                         tzinfo=dt.timezone.utc))[0], 'pass')
        metadata['expected_updated_at'] = '2026-11-18T10:00:00'
        with self.assertRaisesRegex(ValueError, 'timezone'):
            monitor.check_freshness(metadata)

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

