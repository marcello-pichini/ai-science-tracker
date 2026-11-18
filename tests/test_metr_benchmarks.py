"""METR version, human-time units, intervals and guarded refresh regressions."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('metr_import', ROOT / 'scripts/import_public_benchmarks.py')
IMPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORT)
sys.path.insert(0, str(ROOT / 'scripts'))
import refresh_public_benchmarks as REFRESH
sys.path.pop(0)


def fixture():
    baseline = {'benchmark_name': 'METR-Horizon-v1.0', 'release_date': '2020-05-28',
                'scaffolds': ['modular-public', None], 'metrics': {
                    'p50_horizon_length': {'estimate': 0, 'ci_low': 0, 'ci_high': 1},
                    'p80_horizon_length': {'estimate': 0, 'ci_low': None, 'ci_high': None}}}
    current = {'benchmark_name': 'METR-Horizon-v1.1', 'release_date': '2026-04-07',
               'scaffolds': ['metr_agents/react'], 'metrics': {
                    'p50_horizon_length': {'estimate': 1044.780145, 'ci_low': 508.876789, 'ci_high': 3304.261235},
                    'p80_horizon_length': {'estimate': 185.911829, 'ci_low': 97.30292, 'ci_high': 398.514614}}}
    return {'metr-th-1-1': {'benchmark_name': 'METR-Horizon-v1.1', 'long_tasks_version': 'task-v11',
                'results': {'exact_current_alias': current, 'old_alias': copy.deepcopy(baseline)}},
            'metr-th-1-0': {'benchmark_name': 'METR-Horizon-v1.0', 'long_tasks_version': 'task-v10',
                'results': {'old_alias': baseline}}}


def parse(data):
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        inputs = {}
        for key, value in data.items():
            (directory / key).write_text(json.dumps(value))
            inputs[key] = {'file': key, 'source_url': 'https://metr.org/assets/' + key + '.yaml'}
        return IMPORT.parse_records('metr', inputs, directory)


class METRTests(unittest.TestCase):
    def test_both_thresholds_preserve_source_minutes_and_95_percent_intervals(self):
        rows = parse(fixture())
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]['value'], 1044.780145)
        self.assertEqual(rows[0]['unit'], 'human-baseline minutes')
        self.assertEqual(rows[0]['interval']['low'], 508.876789)
        self.assertEqual(rows[0]['interval']['high'], 3304.261235)
        self.assertEqual(rows[0]['interval']['level_percent'], 95)
        self.assertIn('16 hours', rows[0]['caution'])
        self.assertIsNone(rows[1]['caution'])
        self.assertIn('50%', rows[0]['metric'])
        self.assertIn('80%', rows[1]['metric'])
        self.assertEqual(rows[0]['date'], '2026-04-07')
        self.assertIn('not reported', rows[0]['date_basis'])

    def test_stitched_v10_baseline_is_retained_once_under_actual_suite(self):
        rows = parse(fixture())
        old = [r for r in rows if r['model'] == 'old_alias']
        self.assertEqual(len(old), 2)
        self.assertTrue(all('v1.0' in r['comparison_group'] for r in old))
        self.assertEqual(old[0]['details']['long_tasks_version'], 'task-v10')
        self.assertEqual(old[0]['details']['scaffolds'], ['modular-public', None])

    def test_conflicting_stitched_baseline_or_new_suite_holds_component(self):
        data = fixture()
        data['metr-th-1-1']['results']['old_alias']['metrics']['p50_horizon_length']['estimate'] = 1
        with self.assertRaisesRegex(ValueError, 'Conflicting inherited'):
            parse(data)
        data = fixture()
        data['metr-th-1-1']['benchmark_name'] = 'METR-Horizon-v2'
        with self.assertRaisesRegex(ValueError, 'version/schema changed'):
            parse(data)

    def test_zero_missing_intervals_and_nonfinite_negative_reversed_values(self):
        rows = parse(fixture())
        self.assertEqual(rows[-1]['value'], 0)
        self.assertIsNone(rows[-1]['interval']['low'])
        for key, value in [('estimate', float('inf')), ('estimate', -1), ('ci_low', True), ('ci_low', 4000)]:
            data = fixture()
            data['metr-th-1-1']['results']['exact_current_alias']['metrics']['p50_horizon_length'][key] = value
            with self.assertRaises(ValueError):
                parse(data)

    def test_duplicate_yaml_identities_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate METR'):
            IMPORT.metr_yaml('results:\n  repeated: 1\n  repeated: 2\n')

    def test_new_conflicting_export_license_is_not_silently_accepted(self):
        data = fixture()
        data['metr-th-1-1']['license'] = 'CC BY-NC 4.0'
        with self.assertRaisesRegex(ValueError, 'license requires review'):
            parse(data)

    def test_endpoint_expansion_is_rejected_before_public_numerical_fetch(self):
        manifest = json.loads((ROOT / 'scripts/public-benchmark-inputs.json').read_text())
        source = copy.deepcopy(next(s for s in manifest['sources'] if s['id'] == 'metr'))
        modified = copy.deepcopy(manifest)
        next(i for i in modified['inputs'] if i['id'] == 'metr-th-1-1')['download_url'] = 'https://example.org/other-data'
        legal = (ROOT / 'docs/benchmark-licenses/cc-by-4.0.txt').read_bytes()
        with tempfile.TemporaryDirectory() as tmp, patch.object(REFRESH, 'fetch', return_value=legal) as request:
            with self.assertRaisesRegex(ValueError, 'endpoint expansion'):
                REFRESH.prepare(source, modified, Path(tmp))
            self.assertEqual(request.call_count, 1)

    def test_public_component_records_permission_and_inactive_source_without_private_mail(self):
        data = json.loads((ROOT / 'data/benchmarks/metr.json').read_text())
        self.assertEqual(data['license'], 'CC BY 4.0')
        self.assertEqual(data['permission_confirmed_on'], '2026-11-18')
        self.assertFalse(data['source_status']['actively_updated'])
        self.assertEqual(data['source_status']['page_last_updated'], '2026-09-08')
        self.assertTrue(all(r['interval']['level_percent'] == 95 for r in data['records']))
        self.assertNotIn('@metr.org', json.dumps(data))
        self.assertNotIn('mail_message_id', json.dumps(data))


if __name__ == '__main__':
    unittest.main()
