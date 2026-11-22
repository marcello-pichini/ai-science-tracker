"""Monitoring catches content drift even when counts and HTTP status look healthy."""
import datetime as dt
import hashlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit
from zipfile import ZipFile

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
            for inspect in (False, True):
                with self.subTest(inspect=inspect), self.assertRaisesRegex(ValueError, 'size limit'):
                    monitor.fetch('https://site.test/', attempts=1, inspect=inspect, max_bytes=3)

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

            good = monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=fetch)
            self.assertEqual([r['check'] for r in good if r['status'] != 'pass'], ['zenodo/archive-integrity'])

            def stale_fetch(url):
                if '/data/benchmarks/sample.json' in url:
                    return b'{"score": 2}'
                if '/assets/app.js' in url:
                    return b'old-version'
                if urlsplit(url).netloc == 'hf.test' and 'discoveries.json' in url:
                    return b'[{"id":"different"}]'
                return fetch(url)
            bad = monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=stale_fetch)
            failed = {r['check'] for r in bad if r['status'] == 'fail'}
            self.assertEqual(failed, {'asset/assets/app.js', 'hugging-face/discoveries.json', 'site/data/benchmarks/sample.json', 'zenodo/archive-integrity'})
            registry['sources'][0]['path'] = '../private.json'
            registry_path.write_text(json.dumps(registry))
            with self.assertRaisesRegex(ValueError, 'Unsafe component path'):
                monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=fetch)
            registry_path.write_text('{invalid')
            with self.assertRaises(ValueError):
                monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=fetch)
            registry_path.unlink()
            with self.assertRaisesRegex(ValueError, 'Benchmark registry missing'):
                monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=fetch)

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
            (root / 'api/v1/manifest.json').write_text(json.dumps({'components': {
                'citations': {'path': 'data/citations.json', 'sha256': hashlib.sha256(raw).hexdigest()},
                'models': {'path': 'data/models.json', 'sha256': hashlib.sha256(raw).hexdigest()},
            }}))
            (root / 'data/models.json').unlink()
            (root / 'assets').mkdir()
            (root / 'assets/app.js').write_text('current-version')
            write_sample_pages(root)
            def fetch(url):
                path = urlsplit(url).path.lstrip('/')
                if path.endswith('.html'):
                    return sample_page(path)
                if urlsplit(url).netloc == 'hf.test':
                    return (root / 'data' / Path(path).name).read_bytes()
                if path in ('data/citations.json', 'api/v1/manifest.json'):
                    return (root / path).read_bytes() + b'\n'
                return (root / path).read_bytes()
            results = monitor.check(root, 'https://site.test/', 'https://hf.test/', fetcher=fetch, allow_legacy_benchmarks=True)
            failed = {r['check']: r['detail'] for r in results if r['status'] == 'fail'}
            self.assertEqual(set(failed), {'site/data/citations.json', 'site/data/models.json', 'site/api/v1/manifest.json', 'zenodo/archive-integrity'})
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
        old = b'{"metadata":{"version":"v2026.11.17"}}'
        for hour, status in ((11, 'pending'), (13, 'fail')):
            now = dt.datetime(2026, 11, 18, hour, tzinfo=dt.timezone.utc)
            result, = monitor.check_zenodo(release, b'', None, lambda _: old, now)
            self.assertEqual(result['status'], status)

    def test_zenodo_checks_release_bytes_separately_from_deployed_parity(self):
        component = b'archived data'
        components = {'sample': {'path': 'data/sample.json',
                                 'sha256': hashlib.sha256(component).hexdigest(),
                                 'bytes': len(component), 'license': 'CC BY-NC 4.0'}}
        snapshot = hashlib.sha256(json.dumps(
            components, ensure_ascii=False, sort_keys=True, separators=(',', ':')
        ).encode()).hexdigest()
        manifest = json.dumps({'snapshot_sha256': snapshot, 'components': components}).encode()
        release = {'tagName': 'v2026.11.18', 'publishedAt': '2026-11-18T10:00:00Z',
                   'targetSha': 'a' * 40}
        zip_url = 'https://zenodo.org/api/records/42/files/archive.zip/content'

        def run_case(payload, deployed, checksum=None, streamed=False, size_delta=0):
            stream = BytesIO()
            with ZipFile(stream, 'w') as archive:
                prefix = 'owner-repo-aaaaaaa/'
                archive.writestr(prefix + 'api/v1/manifest.json', manifest)
                archive.writestr(prefix + 'data/sample.json', payload)
                if streamed:
                    archive.writestr(prefix + 'padding', b'x' * (1024 * 1024))
            zipped = stream.getvalue()
            metadata = {'doi': '10.5281/zenodo.42', 'id': 42,
                        'conceptdoi': '10.5281/zenodo.24217686',
                        'metadata': {'version': release['tagName'], 'license': {'id': 'cc-by-4.0'}},
                        'files': [{'key': 'archive.zip', 'size': len(zipped) + size_delta,
                                   'checksum': checksum or 'md5:' + hashlib.md5(zipped).hexdigest(),
                                   'links': {'self': zip_url}}]}
            class ArchiveResponse(BytesIO):
                def read(self, size=-1):
                    if not 0 < size <= 1024 * 1024:
                        raise AssertionError('ZIP download must read in bounded chunks')
                    return super().read(size)

            def open_url(request, timeout):
                if request.full_url == zip_url:
                    if streamed:
                        return ArchiveResponse(zipped)
                    return BytesIO(zipped)
                return BytesIO(json.dumps(metadata).encode())

            with patch.object(monitor, 'urlopen', side_effect=open_url), patch.object(monitor.time, 'sleep'):
                results = monitor.check_zenodo(release, manifest, deployed, monitor.fetch)
            return {r['check']: r for r in results}

        earlier = run_case(component, 'b' * 64)
        integrity = earlier['zenodo/archive-integrity']
        self.assertEqual(integrity['status'], 'pass')
        self.assertIn(release['targetSha'], integrity['detail'])
        self.assertIn('10.5281/zenodo.42', integrity['detail'])
        self.assertIn(snapshot, integrity['detail'])
        self.assertEqual(earlier['zenodo/deployed-parity']['status'], 'different')
        self.assertEqual(earlier['zenodo/license-metadata']['status'], 'warning')
        self.assertEqual(run_case(component, snapshot)['zenodo/deployed-parity']['status'], 'pass')
        self.assertEqual(run_case(component, snapshot, streamed=True)['zenodo/deployed-parity']['status'], 'pass')
        self.assertEqual(run_case(b'altered data!', snapshot)['zenodo/archive-integrity']['status'], 'fail')
        self.assertEqual(run_case(component, snapshot, 'md5:' + '0' * 32)['zenodo/archive-integrity']['status'], 'fail')
        for delta, detail in ((-1, 'Response exceeds'), (1, 'ZIP length')):
            with self.subTest(size_delta=delta):
                result = run_case(component, snapshot, size_delta=delta)['zenodo/archive-integrity']
                self.assertEqual(result['status'], 'fail')
                self.assertIn(detail, result['detail'])



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

