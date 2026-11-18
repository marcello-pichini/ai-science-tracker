"""Import official SWE-bench Verified mini-SWE-agent results, preserving CC BY-NC."""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://github.com/SWE-bench/swe-bench.github.io/blob/master/data/leaderboards.json'
LICENSE = 'https://creativecommons.org/licenses/by-nc/4.0/'


def numeric(value, maximum=None):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean source number')
    result = float(value)
    if not math.isfinite(result) or result < 0 or maximum is not None and result > maximum:
        raise ValueError('Invalid source number')
    return result


def build(source, fetched_on):
    datetime.date.fromisoformat(fetched_on)
    boards = [b for b in source['leaderboards'] if b['name'] == 'Verified']
    if len(boards) != 1:
        raise ValueError('Expected one Verified leaderboard')
    records, excluded = [], 0
    for row in boards[0]['results']:
        if row.get('agent') != 'mini-SWE-agent':
            continue
        # Do not silently promote withdrawn or warning-marked submissions.
        if row.get('warning'):
            excluded += 1
            continue
        score = numeric(row.get('resolved'), 100)
        if score is None:
            excluded += 1
            continue
        version = row.get('mini-swe-agent_version')
        if not version or not row.get('folder') or not row.get('name'):
            raise ValueError('Missing evaluation identity or agent version')
        datetime.date.fromisoformat(row['date'])
        records.append({
            'id': row['folder'], 'name': row['name'],
            'model_display': row.get('model_display'), 'organization': row.get('model_org'),
            'agent': row['agent'], 'agent_version': version,
            'reasoning_effort': row.get('reasoning_effort'),
            'score': score, 'mean_cost_usd': numeric(row.get('instance_cost')),
            'evaluation_date': row['date'], 'source_checked': row.get('checked'),
            'settings': row.get('tags', []),
            'source_url': 'https://www.swebench.com/',
        })
    if not records or len({r['id'] for r in records}) != len(records):
        raise ValueError('Empty results or duplicate evaluation identities')
    records.sort(key=lambda r: (r['agent_version'], -r['score'], r['id']))
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        'name': 'SWE-bench Verified — mini-SWE-agent', 'fetched_on': fetched_on,
        'source_url': SOURCE, 'selection_sha256': digest,
        'license': 'CC BY-NC 4.0', 'license_url': LICENSE,
        'license_notice': 'docs/swe-bench-license.txt',
        'attribution': 'SWE-bench Team, SWE-bench website leaderboard',
        'changes': 'Selected Verified mini-SWE-agent runs; omitted warning-marked and unscored runs; renamed fields and sorted records. No scores recalculated.',
        'scope': 'Source-reported evaluation runs, not unique models or independent reproductions. No inferred join to Epoch models. Agent versions and reasoning settings differ.',
        'excluded_runs': excluded, 'records': records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--fetched-on', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/swe-bench.json')
    args = parser.parse_args()
    result = build(json.loads(args.source.read_text()), args.fetched_on)
    # Fetching an unchanged selection does not advance its snapshot date.
    if args.output.exists():
        previous = json.loads(args.output.read_text())
        if previous.get('selection_sha256') == result['selection_sha256']:
            result['fetched_on'] = previous['fetched_on']
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(f"SWE-bench: {len(result['records'])} evaluation runs; snapshot {result['fetched_on']}")


if __name__ == '__main__':
    main()
