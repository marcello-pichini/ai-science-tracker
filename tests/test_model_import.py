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
