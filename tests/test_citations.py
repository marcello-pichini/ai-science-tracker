import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fetch_citations', ROOT / 'scripts/fetch_citations.py')
citations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(citations)


class CitationImportTests(unittest.TestCase):
    def work(self):
        return {'doi': 'https://doi.org/10.1234/published', 'locations': [],
                'publication_date': '2020-01-01', 'cited_by_count': 12,
                'citation_normalized_percentile': {'value': 0.95, 'is_in_top_1_percent': False,
                                                   'is_in_top_10_percent': True}}

    def run_import(self, work, doi='10.1234/published', fetcher=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/discoveries.json').write_text(json.dumps([
                {'id': 'example', 'paper_url': 'https://doi.org/' + doi, 'source_url': ''}]))
            output = root / 'data/citations.json'
            output.write_text('previous snapshot')
            with patch.object(citations, 'ROOT', root), patch.object(citations, 'fetch', side_effect=fetcher or (lambda dois: [work])), redirect_stdout(io.StringIO()):
                try:
                    citations.main()
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    return exc, output.read_text()
            return None, output.read_text()

    def test_location_doi_matches_preprint_and_keeps_canonical_provenance(self):
        work = self.work()
        work['locations'] = [{'doi': 'https://doi.org/10.1234/preprint'}]
        error, output = self.run_import(work, doi='10.1234/preprint')
        self.assertIsNone(error)
        self.assertEqual(json.loads(output)['records']['example'], {
            'doi': '10.1234/published', 'percentile': 95.0, 'top_1': False,
            'top_10': True, 'cited_by': 12})

    def test_flood_hub_predecessor_metrics_belong_only_to_march(self):
        discoveries = json.loads((ROOT / 'data/discoveries.json').read_text())
        by_id = {record['id']: record for record in discoveries}
        rows = json.loads((ROOT / 'data/citations.json').read_text())['records']
        newer = '2024-11-flood-hub-globale'
        earlier = '2024-03-previsione-alluvioni'
        self.assertEqual(citations.doi_of(by_id[earlier]), '10.1038/s41586-024-07145-1')
        self.assertIsNone(citations.doi_of(by_id[newer]))
        self.assertIn(earlier, rows)
        self.assertNotIn(newer, rows)

    def test_singleton_match_preserves_identity_when_location_alias_is_not_returned(self):
        error, output = self.run_import(self.work(), doi='10.1234/preprint')
        self.assertIsNone(error)
        self.assertIn('example', json.loads(output)['records'])

    def test_invalid_external_metrics_preserve_snapshot(self):
        for field, values in [
            ('cited_by_count', ['<b>12</b>', -1, 1.2, True, float('inf')]),
            ('publication_date', ['2025-02-29', '20250101', 'invalid']),
            ('doi', ['https://doi.org/10.1234/paper"><b>']),
            ('value', [-0.1, 1.1, float('nan'), float('inf'), True, '0.9']),
            ('is_in_top_1_percent', [1, 'false', None]),
            ('is_in_top_10_percent', [0, 'true', None]),
        ]:
            for value in values:
                with self.subTest(field=field, value=value):
                    work = self.work()
                    target = work['citation_normalized_percentile'] if field in work['citation_normalized_percentile'] else work
                    target[field] = value
                    error, output = self.run_import(work)
                    self.assertIsNotNone(error)
                    self.assertEqual(output, 'previous snapshot')

    def test_missing_percentile_is_omitted_without_changing_valid_zero_metrics(self):
        work = self.work()
        work['cited_by_count'] = 0
        work['citation_normalized_percentile']['value'] = 0
        error, output = self.run_import(work)
        self.assertIsNone(error)
        self.assertEqual(json.loads(output)['records']['example']['percentile'], 0)
        work['citation_normalized_percentile'] = None
        error, output = self.run_import(work)
        self.assertIsNone(error)
        self.assertEqual(json.loads(output)['records'], {})

    def test_replacement_failure_preserves_previous_snapshot(self):
        with patch('os.replace', side_effect=OSError('replace failed')):
            error, output = self.run_import(self.work())
        self.assertIsInstance(error, OSError)
        self.assertEqual(output, 'previous snapshot')

    def test_fetch_requests_location_aliases(self):
        response = io.BytesIO(json.dumps({'results': [self.work()]}).encode())
        with patch.object(citations.urllib.request, 'urlopen', return_value=response) as request:
            works = citations.fetch(['10.1234/preprint'])
        self.assertEqual(works[0]['cited_by_count'], 12)
        query = citations.urllib.parse.parse_qs(citations.urllib.parse.urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual(query['filter'], ['doi:10.1234/preprint'])
        self.assertIn('locations', query['select'][0].split(','))
