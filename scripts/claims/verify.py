"""Check a claim submission against its machine-checkable target.

Usage: python3 scripts/claims/verify.py CLAIM_ID SUBMISSION_FILE
Prints one JSON line {"claim", "verified", "detail"} and exits 0 only when the target is beaten.
"Verified" means the submission beats the baseline recorded in data/claim-baselines; it is not a
literature novelty check, which a maintainer still does before a claim is marked solved.
"""
import csv, json, subprocess, sys, tempfile
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load_claim(claim_id):
    for c in json.loads((ROOT / 'data/claims.json').read_text())['claims']:
        if c['id'] == claim_id:
            return c
    raise SystemExit(f'unknown claim id: {claim_id}')


def baseline(c):
    return list(csv.DictReader((ROOT / c['target']['baseline_file']).read_text().splitlines()))


# --- Mutually orthogonal Latin squares -------------------------------------------------------
def read_mols(text):
    nums = [list(map(int, l.split())) for l in text.splitlines() if l.strip() and not l.lstrip().startswith('#')]
    (n, k), rows = nums[0], nums[1:]
    if len(rows) != n * k or any(len(r) != n for r in rows):
        raise ValueError(f'expected {k} squares of {n} rows with {n} entries each')
    return n, k, [rows[i * n:(i + 1) * n] for i in range(k)]


def check_mols(n, k, squares):
    full = set(range(n))
    for s, L in enumerate(squares):
        for i in range(n):
            if set(L[i]) != full or {L[r][i] for r in range(n)} != full:
                return f'square {s} is not a Latin square of order {n} (row or column {i})'
    for a in range(k):
        for b in range(a + 1, k):
            if len({(squares[a][i][j], squares[b][i][j]) for i in range(n) for j in range(n)}) != n * n:
                return f'squares {a} and {b} are not orthogonal'
    return None


def verify_mols(c, text):
    n, k, squares = read_mols(text)
    best = {int(r['n']): int(r['lower']) for r in baseline(c)}
    if n not in best:
        return False, f'order {n} is outside the baseline table'
    err = check_mols(n, k, squares)
    if err:
        return False, err
    if k <= best[n]:
        return False, f'valid: {k} MOLS of order {n}, but the baseline already has N({n}) >= {best[n]}'
    return True, f'{k} MOLS of order {n} beat the baseline N({n}) >= {best[n]}'


# --- Best-Fit in random order ----------------------------------------------------------------
def expected_bins(items, C):
    """Exact expected number of bins Best-Fit opens when the items arrive in uniformly random order."""
    sizes = sorted(set(items))

    def alive(loads, counts):
        smin = next((s for s, c in zip(sizes, counts) if c), None)
        return () if smin is None else tuple(sorted(l for l in loads if C - l >= smin))

    @lru_cache(maxsize=None)
    def f(counts, loads):
        n, total = sum(counts), Fraction(0)
        if n == 0:
            return total
        for t, c in enumerate(counts):
            if not c:
                continue
            s, nc = sizes[t], counts[:t] + (c - 1,) + counts[t + 1:]
            fit = [i for i, l in enumerate(loads) if l + s <= C]
            if fit:
                j = max(fit, key=lambda i: loads[i])
                nl, opened = loads[:j] + (loads[j] + s,) + loads[j + 1:], 0
            else:
                nl, opened = loads + (s,), 1
            total += c * (opened + f(nc, alive(nl, nc)))
        return total / n

    return f(tuple(items.count(s) for s in sizes), ())


def verify_bin_packing(c, text):
    sub = json.loads(text)
    C, items, packing = int(sub['capacity']), [int(x) for x in sub['items']], sub['packing']
    limit = c['target']['max_items']
    if not 0 < len(items) <= limit or any(not 0 < x <= C for x in items):
        return False, f'need 1..{limit} items with integer sizes in 1..capacity'
    if sorted(x for b in packing for x in b) != sorted(items) or any(sum(b) > C for b in packing):
        return False, 'the packing must use every item exactly once and respect the capacity'
    ratio = expected_bins(items, C) / len(packing)       # len(packing) >= OPT, so ratio <= E[BF]/OPT
    threshold = Fraction(c['target']['threshold'])
    if ratio <= threshold:
        return False, f'E[BF]/bins = {ratio} ({float(ratio):.6f}) does not exceed {threshold}'
    return True, f'E[BF]/OPT >= {ratio} ({float(ratio):.6f}) > {threshold}'


# --- Linear codes ----------------------------------------------------------------------------
def verify_linear_code(c, text):
    q, n, k = map(int, text.split()[:3])
    t = c['target']
    if (q, n) != (t['q'], t['n']):
        return False, f'this claim is for q={t["q"]}, n={t["n"]}'
    row = next((r for r in baseline(c) if int(r['k']) == k), None)
    if row is None:
        return False, f'no baseline for k={k}'
    lower, upper = int(row['lower']), int(row['upper'])
    if lower == upper:
        return False, f'k={k} is already closed (d = {lower})'
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / 'bz'
        subprocess.run(['cc', '-O2', '-o', str(exe), str(HERE / 'bz.c')], check=True)
        out = subprocess.run([str(exe), str(lower + 1)], input=text, capture_output=True, text=True,
                             timeout=t.get('timeout_seconds', 3000))
    if out.returncode:
        return False, 'the matrix is malformed or has rank below k'
    line = out.stdout.splitlines()[0]          # 'd >= D (upper X)', 'd = X < D' or exact 'd = X'
    exact = line.startswith('d = ') and '<' not in line
    if line.startswith('d >= ') or (exact and int(line.split()[2]) > lower):
        return True, f'[{n},{k}] code over GF({q}): {line.strip()}, above the baseline lower bound {lower}'
    return False, f'{line.strip()} (baseline lower bound {lower})'


CHECKS = {'mols-lower-bound': verify_mols, 'bin-packing-random-order': verify_bin_packing,
          'linear-code-record': verify_linear_code}


def verify(claim_id, text):
    c = load_claim(claim_id)
    try:
        return CHECKS[c['target']['type']](c, text)
    except (ValueError, KeyError, TypeError, IndexError) as e:
        return False, f'malformed submission: {e}'


if __name__ == '__main__':
    cid, path = sys.argv[1:3]
    ok, detail = verify(cid, Path(path).read_text())
    print(json.dumps({'claim': cid, 'verified': ok, 'detail': detail}))
    sys.exit(0 if ok else 1)
