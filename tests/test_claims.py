import csv, json, re, shutil, tempfile, unittest
from fractions import Fraction
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'claims'))
import verify  # noqa: E402

DATA = json.loads((ROOT / 'data/claims.json').read_text())
STATUSES = {'open', 'claimed', 'submitted', 'solved', 'retired'}
REASONS = {'no_improvement', 'out_of_time', 'statement_seems_false', 'too_hard', 'other'}


def mols_text(n, k):
    squares = [[[(a * i + j) % n for j in range(n)] for i in range(n)] for a in range(1, k + 1)]
    return f'{n} {k}\n' + '\n'.join(' '.join(map(str, r)) for s in squares for r in s)


class ClaimsData(unittest.TestCase):
    def test_records(self):
        ids = {d['id'] for d in json.loads((ROOT / 'data/discoveries.json').read_text())}
        seen = set()
        for c in DATA['claims']:
            self.assertRegex(c['id'], r'^[a-z0-9]+(-[a-z0-9]+)*$')
            self.assertNotIn(c['id'], seen); seen.add(c['id'])
            self.assertIn(c['parent_discovery_id'], ids, c['id'])
            self.assertIn(c['status'], STATUSES)
            self.assertIn(c['target']['type'], verify.CHECKS)
            self.assertTrue(c['title'] and c['statement'] and c['target']['format'])
            self.assertTrue(c['baseline']['sources'])
            for s in c['baseline']['sources']:
                self.assertTrue(s['url'].startswith('https://'))
            if 'baseline_file' in c['target']:
                self.assertTrue((ROOT / c['target']['baseline_file']).exists())
            self.assertRegex(c['added_date'], r'^\d{4}-\d{2}-\d{2}$')
            for a in c['attempts']:
                self.assertTrue(a['handle'] and a['agent'] and a['model'] and a['summary'])
                self.assertIn(a['outcome'], {'released', 'submitted', 'rejected', 'verified'})
                if a['outcome'] == 'released':
                    self.assertIn(a['reason'], REASONS)


class Verifiers(unittest.TestCase):
    def claim(self, ctype, rows, **target):
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp)
        f = tmp / 'b.csv'
        with open(f, 'w', newline='') as h:
            w = csv.writer(h); w.writerow(rows[0]); w.writerows(rows[1:])
        return {'target': {'type': ctype, 'baseline_file': str(f), **target}}

    def test_mols(self):
        c = self.claim('mols-lower-bound', [['n', 'lower'], [5, 3]])
        self.assertTrue(verify.verify_mols(c, mols_text(5, 4))[0])
        self.assertFalse(verify.verify_mols(c, mols_text(5, 3))[0])           # does not beat 3
        bad = mols_text(5, 4).replace('0 1 2 3 4', '1 0 2 3 4', 1)
        self.assertIn('not a Latin square', verify.verify_mols(c, bad)[1])
        c2 = self.claim('mols-lower-bound', [['n', 'lower'], [7, 1]])
        twice = '7 2\n' + '\n'.join(mols_text(7, 1).splitlines()[1:] * 2)  # identical squares
        self.assertIn('not orthogonal', verify.verify_mols(c2, twice)[1])

    def test_best_fit_expectation(self):
        # Co-FunSearch family (arXiv 2601.16849): m items of size m+1 and m+1 of size m, capacity m(m+1), OPT 2.
        m = 3
        items = [m + 1] * m + [m] * (m + 1)
        e = verify.expected_bins(items, m * (m + 1))
        self.assertTrue(Fraction(2) < e < Fraction(3))
        c = {'target': {'type': 'bin-packing-random-order', 'threshold': '3/2', 'max_items': 30}}
        sub = json.dumps({'capacity': 12, 'items': items, 'packing': [[4, 4, 4], [3, 3, 3, 3]]})
        ok, detail = verify.verify_bin_packing(c, sub)
        self.assertFalse(ok); self.assertIn(str(e / 2), detail)
        self.assertFalse(verify.verify_bin_packing(c, json.dumps({'capacity': 12, 'items': items, 'packing': [items]}))[0])
        # a deliberately bad certificate with too few bins cannot pass: the packing is checked
        self.assertIn('capacity', verify.verify_bin_packing(c, json.dumps({'capacity': 12, 'items': items, 'packing': [[4, 4, 4, 3], [3, 3, 3]]}))[1])

    @unittest.skipUnless(shutil.which('cc'), 'needs a C compiler')
    def test_linear_code(self):
        # [7,4] Hamming code over GF(2) has d = 3.
        G = '2 7 4\n1 0 0 0 1 1 0\n0 1 0 0 1 0 1\n0 0 1 0 0 1 1\n0 0 0 1 1 1 1\n'
        beat = self.claim('linear-code-record', [['q', 'n', 'k', 'lower', 'upper'], [2, 7, 4, 2, 3]], q=2, n=7)
        self.assertTrue(verify.verify_linear_code(beat, G)[0])
        known = self.claim('linear-code-record', [['q', 'n', 'k', 'lower', 'upper'], [2, 7, 4, 3, 4]], q=2, n=7)
        self.assertFalse(verify.verify_linear_code(known, G)[0])
        self.assertIn('q=3', verify.verify_linear_code(self.claim('linear-code-record', [['q', 'n', 'k', 'lower', 'upper']], q=3, n=7), G)[1])


if __name__ == '__main__':
    unittest.main()
