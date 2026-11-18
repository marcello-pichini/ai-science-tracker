"""Daily refresh preserves rights boundaries and last accepted components."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import refresh_public_benchmarks as REFRESH
sys.path.pop(0)


class BenchmarkRefreshTests(unittest.TestCase):
    def test_new_root_notice_stops_before_result_downloads(self):
        manifest = json.loads((ROOT / 'scripts/public-benchmark-inputs.json').read_text())
        source = next(s for s in manifest['sources'] if s['id'] == 'mmlu-pro')
        replies = [json.dumps({'object': {'sha': 'a' * 40}}).encode(),
                   json.dumps({'tree': [{'path': 'NOTICE.txt'}]}).encode()]
        with tempfile.TemporaryDirectory() as tmp, patch.object(REFRESH, 'fetch', side_effect=replies) as request:
            with self.assertRaisesRegex(ValueError, 'NOTICE requires review'):
                REFRESH.prepare(source, manifest, Path(tmp))
            self.assertEqual(request.call_count, 2)

    def test_dataset_license_change_holds_before_numerical_collection(self):
        manifest = json.loads((ROOT / 'scripts/public-benchmark-inputs.json').read_text())
        source = next(s for s in manifest['sources'] if s['id'] == 'arena')
        reply = json.dumps({'sha': 'b' * 40, 'cardData': {'license': 'cc-by-nc-4.0'}}).encode()
        with tempfile.TemporaryDirectory() as tmp, patch.object(REFRESH, 'fetch', return_value=reply) as request:
            with self.assertRaisesRegex(ValueError, 'license changed'):
                REFRESH.prepare(source, manifest, Path(tmp))
            self.assertEqual(request.call_count, 1)

    def test_changed_legal_text_holds_before_scores(self):
        manifest = json.loads((ROOT / 'scripts/public-benchmark-inputs.json').read_text())
        source = next(s for s in manifest['sources'] if s['id'] == 'gpqa')
        with tempfile.TemporaryDirectory() as tmp, patch.object(REFRESH, 'fetch', return_value=b'New legal terms'):
            with self.assertRaisesRegex(ValueError, 'License text changed'):
                REFRESH.prepare(source, manifest, Path(tmp))

    def test_unrelated_revision_and_retrieval_date_do_not_change_semantic_snapshot(self):
        data = json.loads((ROOT / 'data/benchmarks/arena.json').read_text())
        candidate = copy.deepcopy(data)
        candidate.update(retrieved_on='2026-11-19', upstream_revision='a' * 40)
        for row in candidate['records']:
            row['source_url'] = 'https://example.org/new-revision'
        self.assertEqual(REFRESH.semantic(data), REFRESH.semantic(candidate))
        candidate['records'][0]['value'] += 1
        self.assertNotEqual(REFRESH.semantic(data), REFRESH.semantic(candidate))

    def test_blocked_source_keeps_previous_bytes_and_writes_no_public_status_churn(self):
        manifest = {'retrieved_on': '2026-11-18', 'inputs': [], 'sources': [{'id': 'blocked'}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'data/benchmarks'
            output.mkdir(parents=True)
            manifest_path = root / 'manifest.json'
            manifest_path.write_bytes(REFRESH.encode(manifest))
            old_manifest = manifest_path.read_bytes()
            (output / 'blocked.json').write_text('Previous valid bytes')
            with patch.object(REFRESH, 'prepare', side_effect=ValueError('Changed license')):
                report = REFRESH.refresh(root, manifest_path, output, '2026-11-19')
            self.assertEqual(report['sources'][0]['status'], 'held')
            self.assertEqual((output / 'blocked.json').read_text(), 'Previous valid bytes')
            self.assertEqual(manifest_path.read_bytes(), old_manifest)

    def test_valid_source_updates_despite_another_hold_and_unchanged_day_is_idempotent(self):
        template = json.loads((ROOT / 'scripts/public-benchmark-inputs.json').read_text())
        source = copy.deepcopy(next(s for s in template['sources'] if s['id'] == 'gpqa'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'data/benchmarks'
            output.mkdir(parents=True)
            notice = root / source['license_notice']
            notice.parent.mkdir(parents=True)
            notice.write_bytes((ROOT / source['license_notice']).read_bytes())
            old = json.loads((ROOT / 'data/benchmarks/gpqa.json').read_text())
            old['records'] = old['records'][:1]
            (output / 'gpqa.json').write_bytes(REFRESH.encode(old))
            (output / 'blocked.json').write_text('Previous valid bytes')
            registry = {'sources': [], 'retrieved_on': '2026-11-18'}
            (output / 'index.json').write_bytes(REFRESH.encode(registry))
            # The blocked source still needs a minimal registry identity.
            (output / 'blocked.json').write_bytes(REFRESH.encode({'records': [{'value': 1}]}))
            manifest = {**template, 'sources': [source, {'id': 'blocked', 'inputs': []}]}
            manifest_path = root / 'manifest.json'
            manifest_path.write_bytes(REFRESH.encode(manifest))
            def prepare(current, previous, cache, epoch):
                if current['id'] == 'blocked':
                    raise ValueError('Changed license')
                candidate = copy.deepcopy(old)
                candidate['records'][0]['value'] = 0.5
                return copy.deepcopy(current), [], candidate
            def build(current, meta, cache):
                result = copy.deepcopy(old)
                result['records'][0]['value'] = 0.5
                result['retrieved_on'] = current['retrieved_on']
                return result
            # Mock raw acquisition and parsing; exercise the real merge, file
            # writing, independent date preservation and no-change logic.
            with patch.object(REFRESH, 'prepare', side_effect=lambda c,m,d,e: (prepare(c,m,d,e)[0], [])), patch.object(REFRESH.importer, 'build_component', side_effect=build):
                first = REFRESH.refresh(root, manifest_path, output, '2026-11-19')
                self.assertEqual([s['status'] for s in first['sources']], ['updated', 'held'])
                accepted = (output / 'gpqa.json').read_bytes()
                second = REFRESH.refresh(root, manifest_path, output, '2026-11-20')
                self.assertEqual([s['status'] for s in second['sources']], ['unchanged', 'held'])
                self.assertEqual((output / 'gpqa.json').read_bytes(), accepted)
                self.assertEqual(json.loads(accepted)['retrieved_on'], '2026-11-19')


if __name__ == '__main__':
    unittest.main()
