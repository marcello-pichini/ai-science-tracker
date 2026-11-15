import csv
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ModelImportTests(unittest.TestCase):
    def test_input_fingerprint_and_recognized_schemeless_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'work/epoch').mkdir(parents=True)
            (root / 'data').mkdir()
            csv_path = root / 'work/epoch/notable_ai_models.csv'
            with csv_path.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['Model', 'Organization', 'Publication date', 'Link'])
                writer.writeheader()
                writer.writerows([
                    {'Model': 'Example', 'Organization': 'OpenAI', 'Publication date': '2025-01-01', 'Link': 'arxiv.org/abs/2501.14818'},
                    {'Model': 'Other', 'Organization': 'OpenAI', 'Publication date': '2025-01-02', 'Link': 'example.com/paper'},
                ])
            (root / 'data/discoveries.json').write_text('[]')
            subprocess.run(['python3', str(ROOT / 'scripts/generate_models.py')], cwd=root, check=True, capture_output=True)
            data = json.loads((root / 'data/models.json').read_text())
            self.assertEqual(data['source']['csv_sha256'], hashlib.sha256(csv_path.read_bytes()).hexdigest())
            self.assertNotIn('downloaded', data['source'])
            links = {model['name']: model['link'] for model in data['models']}
            self.assertEqual(links['Example'], 'https://arxiv.org/abs/2501.14818')
            self.assertEqual(links['Other'], 'example.com/paper')

    def run_fixture(self, headers, row, fail_replace=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'work/epoch').mkdir(parents=True)
            (root / 'data').mkdir()
            with (root / 'work/epoch/notable_ai_models.csv').open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                if row is not None:
                    writer.writerow(row)
            (root / 'data/discoveries.json').write_text('[]')
            output = root / 'data/models.json'
            output.write_text('previous snapshot')
            script = str(ROOT / 'scripts/generate_models.py')
            command = ['python3', script]
            if fail_replace:
                command = ['python3', '-c',
                           'import runpy, sys; from unittest.mock import patch; '
                           f'sys.path.insert(0, {str(ROOT / "scripts")!r}); '
                           f'patch("os.replace", side_effect=OSError("replace failed")).start(); runpy.run_path({script!r})']
            result = subprocess.run(command, cwd=root, capture_output=True)
            return result, output.read_text()

    def test_invalid_inputs_preserve_previous_snapshot(self):
        base = {'Model': 'Example', 'Organization': 'OpenAI', 'Publication date': '2025-01-01'}
        cases = [
            ({'Name': 'Example', 'Organization': 'OpenAI', 'Publication date': '2025-01-01'}, None),
            (base, None),
            (base, {'Publication date': '2025-13-99'}),
            (base, {'Publication date': '2025-02-29'}),
            (base, {'Publication date': '20250101'}),
            (base, {'Organization': 'Unrelated lab'}),
        ]
        for metric in ['Parameters', 'Training compute (FLOP)']:
            for value in ['NaN', 'Infinity', '-Infinity', 'invalid']:
                cases.append((base, {metric: value}))
        for fields, override in cases:
            with self.subTest(fields=fields, override=override):
                row = None if override is None and fields == base else {**fields, **(override or {})}
                headers = list(dict.fromkeys([*fields, *(override or {})]))
                result, output = self.run_fixture(headers, row)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, 'previous snapshot')

    def test_empty_optional_numbers_remain_null_and_metrics_keep_their_shape(self):
        fields = {'Model': 'Example', 'Organization': 'OpenAI', 'Publication date': '2024-02-29',
                  'Parameters': '', 'Training compute (FLOP)': '1.2e24'}
        result, output = self.run_fixture(list(fields), fields)
        self.assertEqual(result.returncode, 0, result.stderr)
        model = json.loads(output)['models'][0]
        self.assertIsNone(model['parameters'])
        self.assertEqual(model['compute_flop'], '1.2e24')

    def test_replacement_failure_preserves_previous_snapshot(self):
        fields = {'Model': 'Example', 'Organization': 'OpenAI', 'Publication date': '2025-01-01'}
        result, output = self.run_fixture(list(fields), fields, fail_replace=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'replace failed', result.stderr)
        self.assertEqual(output, 'previous snapshot')
