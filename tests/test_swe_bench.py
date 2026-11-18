"""SWE-bench selection, source fidelity and separate-license regressions."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('swe_import', ROOT / 'scripts/import_swe_bench.py')
IMPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORT)


def fixture():
    row = {'folder': 'run-a', 'name': 'Exact model (high)', 'agent': 'mini-SWE-agent',
           'mini-swe-agent_version': '2.0.0', 'resolved': 0, 'date': '2026-02-17',
           'instance_cost': 0, 'tags': ['Model: exact-model', 'System: Attempts - 1']}
    return {'leaderboards': [{'name': 'Verified', 'results': [row]},
                             {'name': 'Lite', 'results': [{**row, 'resolved': 99}]}]}


class SWESelectionTests(unittest.TestCase):
    def test_selects_only_verified_agent_and_keeps_versions_zero_and_missing_cost(self):
        source = fixture()
        row = source['leaderboards'][0]['results'][0]
        source['leaderboards'][0]['results'] += [
            {**row, 'folder': 'run-b', 'mini-swe-agent_version': '1.0.0', 'instance_cost': None},
            {**row, 'folder': 'other-agent', 'agent': 'Other'},
            {**row, 'folder': 'flagged', 'warning': 'Source warning'},
            {**row, 'folder': 'unscored', 'resolved': None},
        ]
        original = copy.deepcopy(source)
        result = IMPORT.build(source, '2026-11-18')
        self.assertEqual(source, original)
        self.assertEqual({r['id'] for r in result['records']}, {'run-a', 'run-b'})
        self.assertEqual({r['agent_version'] for r in result['records']}, {'1.0.0', '2.0.0'})
        self.assertTrue(all(r['score'] == 0 for r in result['records']))
        self.assertEqual({r['mean_cost_usd'] for r in result['records']}, {0, None})
        self.assertEqual(result['excluded_runs'], 2)
        self.assertEqual(result['license'], 'CC BY-NC 4.0')

    def test_invalid_source_values_and_ambiguous_run_id_fail(self):
        for value in [float('nan'), float('inf'), -1, 101, True]:
            source = fixture()
            source['leaderboards'][0]['results'][0]['resolved'] = value
            with self.assertRaises(ValueError):
                IMPORT.build(source, '2026-11-18')
        source = fixture()
        source['leaderboards'][0]['results'] *= 2
        with self.assertRaises(ValueError):
            IMPORT.build(source, '2026-11-18')

    def test_unchanged_selection_does_not_advance_snapshot_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'source.json', Path(tmp) / 'output.json'
            source.write_text(json.dumps(fixture()))
            for day in ['2026-11-18', '2026-11-19']:
                subprocess.run(['python3', str(ROOT / 'scripts/import_swe_bench.py'), str(source),
                                '--fetched-on', day, '--output', str(output)], check=True, capture_output=True)
            self.assertEqual(json.loads(output.read_text())['fetched_on'], '2026-11-18')

    def test_public_export_retains_separate_license_and_evaluation_identity(self):
        data = json.loads((ROOT / 'data/swe-bench.json').read_text())
        self.assertEqual(data['license'], 'CC BY-NC 4.0')
        self.assertTrue((ROOT / data['license_notice']).exists())
        self.assertGreater(len(data['records']), 0)
        self.assertEqual(len({r['id'] for r in data['records']}), len(data['records']))
        self.assertTrue(all(r['agent'] == 'mini-SWE-agent' and 0 <= r['score'] <= 100 for r in data['records']))
        self.assertNotIn('swe-bench.json', (ROOT / 'scripts/build_hf_dataset.py').read_text())
        self.assertIn('noncommercial reuse only', (ROOT / 'model-progress.html').read_text())
