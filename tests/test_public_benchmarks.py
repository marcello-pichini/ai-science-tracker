"""Numerical fidelity, license boundaries and failure-closed snapshot import."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('public_benchmarks', ROOT / 'scripts/import_public_benchmarks.py')
IMPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORT)


class PublicBenchmarkTests(unittest.TestCase):
    def parse(self, source, fixtures):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            inputs = {}
            for key, value in fixtures.items():
                content = value if isinstance(value, str) else json.dumps(value)
                (directory / key).write_text(content)
                inputs[key] = {'file': key, 'source_url': 'https://example.org/' + key}
            return IMPORT.parse_records(source, inputs, directory)

    def test_component_hashes_notices_and_separate_share_alike_license(self):
        registry = json.loads((ROOT / 'data/benchmarks/index.json').read_text())
        manifest = json.loads((ROOT / 'scripts/public-benchmark-inputs.json').read_text())
        inputs = {i['id']: i for i in manifest['inputs']}
        self.assertEqual(len(registry['sources']), 11)
        total = 0
        for source in registry['sources']:
            content = (ROOT / source['path']).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), source['sha256'])
            data = json.loads(content)
            total += len(data['records'])
            self.assertEqual(len(data['records']), source['record_count'])
            self.assertEqual(len({r['id'] for r in data['records']}), len(data['records']))
            self.assertTrue(data['attribution'] and data['changes'] and data['selection'])
            self.assertEqual(data['license'], source['license'])
            self.assertTrue(all(inputs[k]['sha256'] == v for k, v in data['input_sha256'].items()))
            notice_hash = hashlib.sha256((ROOT / data['license_notice']).read_bytes()).hexdigest()
            self.assertIn(notice_hash, data['input_sha256'].values())
            for forbidden in ['"contact_info"', '"email"', '"messages"', '"trajectory_files"', '"model_scores"']:
                self.assertNotIn(forbidden, content.decode())
        self.assertGreater(total, 0)
        charxiv = json.loads((ROOT / 'data/benchmarks/charxiv.json').read_text())
        self.assertEqual(charxiv['license'], 'CC BY-SA 4.0')
        self.assertIn('share', charxiv['selection'])
        self.assertNotIn('data/benchmarks', (ROOT / 'scripts/build_hf_dataset.py').read_text())

    def test_gpqa_uses_own_mean_scores_and_retains_distinct_configurations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'epoch.zip'
            header = 'Model version,mean_score,Best score (across scorers),Release date,Organization,stderr,Log viewer,Logs,Started at,id\n'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('gpqa_diamond.csv', header +
                    'model_high,0,0.9,2026-01-01,Lab,0.1,,,2026-02-01T00:00:00Z,a\n' +
                    'model_low,0.5,0.8,2026-01-01,Lab,0.1,,,2026-02-01T00:00:00Z,b\n')
                archive.writestr('gpqa_external.csv', 'Unlicensed external score\n99\n')
            rows = IMPORT.parse_records('gpqa', {'epoch-zip': {'file': 'epoch.zip'}}, Path(tmp))
        self.assertEqual([r['value'] for r in rows], [0, 0.5])
        self.assertEqual([r['unit'] for r in rows], ['fraction', 'fraction'])
        self.assertEqual(rows[0]['details']['Best score (across scorers)'], '0.9')
        self.assertEqual(rows[0]['date_basis'], 'Evaluation start')

    def test_arena_requires_complete_pagination_and_selects_overall_only(self):
        item = {'model_name': 'Exact model', 'organization': 'Lab', 'license': 'Proprietary',
                'rating': -0.1, 'rating_lower': -0.2, 'rating_upper': 0.1, 'variance': 0,
                'vote_count': 0, 'rank': 1, 'category': 'overall', 'leaderboard_publish_date': '2026-11-11'}
        page = {'num_rows_total': 2, 'rows': [{'row_idx': 0, 'row': item},
                {'row_idx': 1, 'row': {**item, 'category': 'coding'}}]}
        rows = self.parse('arena', {'arena-page-0': page, 'arena-card': 'Licensed card'})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['value'], -0.1)
        self.assertEqual(rows[0]['unit'], 'rating points')
        with self.assertRaises(ValueError):
            self.parse('arena', {'arena-page-0': {**page, 'num_rows_total': 3}, 'arena-card': ''})
        page['rows'][1]['row_idx'] = 0
        with self.assertRaises(ValueError):
            self.parse('arena', {'arena-page-0': page, 'arena-card': ''})

    def test_tau_keeps_protocols_zero_and_missing_domains_but_excludes_contacts(self):
        submission = {'model_name': 'Exact agent model', 'submission_date': '2026-01-01',
            'contact_info': {'email': 'private@example.org'}, 'trajectory_files': {'task': 'private.json'},
            'methodology': {'tau2_bench_version': '1.0.1', 'user_simulator': 'user-model'},
            'results': {'airline': {'pass_1': 0, 'pass_2': 0, 'cost': None}, 'retail': None}}
        rows = self.parse('tau', {'tau-manifest': {'submissions': ['a']}, 'tau-a': submission})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['value'], 0)
        self.assertIsNone(rows[0]['details']['domain_results']['cost'])
        self.assertIn('1.0.1', rows[0]['comparison_group'])
        self.assertNotIn('private@example.org', json.dumps(rows))
        self.assertNotIn('private.json', json.dumps(rows))

    def test_ruler_preserves_real_zero_and_omits_unmeasured_lengths(self):
        rows = self.parse('ruler', {'ruler': '|[Baseline](https://example.org)|4K||85.6|\n'
            '[Exact](https://example.org) (7B)|8K|4K|90|0|-|TBD||||\n'})
        self.assertEqual([(r['model'], r['value']) for r in rows], [('Baseline', 85.6), ('Exact (7B)', 90), ('Exact (7B)', 0)])

    def test_source_numbers_reject_boolean_nonfinite_and_out_of_scale_values(self):
        for value in [True, 'nan', 'inf', -0.1, 1.1]:
            with self.assertRaises(ValueError):
                IMPORT.row('model', 'accuracy', value, 'fraction', 'https://example.org', 'id')
        self.assertEqual(IMPORT.number('0'), 0)
        self.assertIsNone(IMPORT.number(''))

    def test_changed_input_stops_before_writing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'source').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'Unreviewed input bytes'):
                IMPORT.build({'inputs': [{'id': 'source', 'file': 'source', 'sha256': 'unreviewed'}]}, root, root / 'output')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
