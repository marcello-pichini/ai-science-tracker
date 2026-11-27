"""The home page list component drops only evidence prose and binds each row to its per-record API file."""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dataset_manifest import LIST_OMITTED_EVIDENCE, discovery_list_bytes, record_bytes


class DiscoveryListTests(unittest.TestCase):
    def test_rows_keep_every_list_field_and_bind_to_record_bytes(self):
        records = json.loads((ROOT / 'data/discoveries.json').read_text())
        rows = json.loads(discovery_list_bytes(records))
        self.assertEqual([r['id'] for r in rows], [r['id'] for r in records])
        for record, row in zip(records, rows):
            digest = row.pop('record_sha256')
            self.assertEqual(digest, hashlib.sha256(record_bytes(record)).hexdigest()[:16])
            evidence = row.pop('evidence', None)
            self.assertEqual(row, {k: v for k, v in record.items() if k != 'evidence'})
            if record.get('evidence') is not None:
                kept = {k: v for k, v in record['evidence'].items() if k not in LIST_OMITTED_EVIDENCE}
                if record['evidence'].get('tested') == record['summary']:
                    kept['tested'] = record['summary']
                self.assertEqual(evidence, kept)
        api = ROOT / 'api/v1/discoveries' / (records[0]['id'] + '.json')
        if api.exists():  # Generated output; absent from a source-only checkout.
            self.assertEqual(api.read_bytes(), record_bytes(records[0]))

    def test_record_loader_rejects_bytes_from_another_snapshot(self):
        code = r'''
const assert = require('node:assert/strict'), crypto = require('node:crypto'), loader = require('./assets/catalog-data.js');
const bytes = Buffer.from('{"id":"a"}\n'), digest = crypto.createHash('sha256').update(bytes).digest('hex').slice(0, 16);
const fetch = async url => { assert.ok(url.includes('v=' + digest)); return {ok:true, arrayBuffer:async () => Uint8Array.from(bytes).buffer}; };
(async () => {
  assert.deepEqual(await loader.record('api/v1/discoveries/a.json', digest, {fetch, crypto:crypto.webcrypto}), {id:'a'});
  await assert.rejects(loader.record('api/v1/discoveries/a.json', '0'.repeat(16), {fetch:async () => ({ok:true, arrayBuffer:async () => Uint8Array.from(bytes).buffer}), crypto:crypto.webcrypto}), /mismatch/);
  await assert.rejects(loader.record('api/v1/discoveries/a.json', 'bad', {fetch, crypto:crypto.webcrypto}), /Invalid record digest/);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', code], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
