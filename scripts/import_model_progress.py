"""Build model-progress data from a private Epoch ZIP and the public model catalog."""
import argparse
import csv
import datetime
import hashlib
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABS = {
    'OpenAI': ['OpenAI'],
    'Google DeepMind': ['Google DeepMind', 'Google', 'DeepMind', 'Google Research', 'Google Brain', 'Google AI', 'Google Cloud'],
    'Anthropic': ['Anthropic'], 'Meta': ['Meta AI', 'Meta', 'Facebook AI Research'],
    'Alibaba': ['Alibaba'], 'DeepSeek': ['DeepSeek'], 'xAI': ['xAI'], 'Mistral': ['Mistral AI', 'Mistral'],
}
BENCHMARKS = [
    ('frontiermath_tier_4_v2.csv', 'FrontierMath Tier 4 (v2)', 'Mathematics'),
    ('mirrorcode.csv', 'MirrorCode', 'Software engineering'),
    ('simpleqa_verified.csv', 'SimpleQA Verified', 'World knowledge'),
    ('mystery_game_puzzles.csv', 'Mystery Game Puzzles', 'Reasoning / games'),
]


def number(value):
    if value in (None, ''):
        return None
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Nonfinite source value')
    return value


def lab_for(organization):
    parts = [p.strip() for p in re.split('[,;]', organization)]
    found = {lab for lab, aliases in LABS.items() if any(p in aliases for p in parts)}
    return next(iter(found)) if len(found) == 1 else None


def family_lab(name):
    # Name-based attribution is retained explicitly when source ownership is empty.
    for pattern, lab in [
        (r'^(GPT|ChatGPT|o[134](?:-|\b)|Codex|DALL)', 'OpenAI'),
        (r'^(Gemini|Gemma|PaLM|LaMDA)', 'Google DeepMind'),
        (r'^Claude', 'Anthropic'), (r'^(Llama|OPT-|Galactica|Muse)', 'Meta'),
        (r'^(Qwen|CodeQwen)', 'Alibaba'), (r'^DeepSeek', 'DeepSeek'),
        (r'^Grok', 'xAI'), (r'^(Mistral|Mixtral|Codestral|Ministral|Devstral|Pixtral|Magistral)', 'Mistral'),
    ]:
        if re.search(pattern, name, re.I):
            return lab
    return None


def build(archive, catalog_path, fetched_on):
    datetime.date.fromisoformat(fetched_on)
    with zipfile.ZipFile(archive) as z:
        def rows(name):
            return list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig'))))

        metadata = rows('model_metadata.csv')
        eci = rows('epoch_capabilities_index/eci_scores.csv')
        grouped = defaultdict(list)
        for row in metadata:
            if row['model_group']:
                grouped[row['model_group']].append(row)
        estimates = {r['Model']: r for r in eci}
        catalog_rows = json.loads(catalog_path.read_text())['models']
        aliases = defaultdict(set)
        for row in metadata:
            if row['model_group']:
                for alias in [row['model_group'], row['model_version'], row['display_name']]:
                    if alias:
                        aliases[re.sub(r'[-_\s]+', ' ', alias).strip().casefold()].add(row['model_group'])
        catalog, catalog_aliases = {}, defaultdict(list)
        for row in catalog_rows:
            candidates = aliases.get(re.sub(r'[-_\s]+', ' ', row['name']).strip().casefold(), set())
            name = row['name']
            if len(candidates) == 1:
                candidate = next(iter(candidates))
                if row['date'] in {r['date'] for r in grouped[candidate]}:
                    name = candidate
            catalog.setdefault(name, row)
            catalog_aliases[name].append({'name': row['name'], 'date': row['date'], 'link': row['link']})
        records = {}
        variant_groups = defaultdict(set)
        for row in metadata:
            if row['model_group'] and row['model_version']:
                variant_groups[row['model_version']].add(row['model_group'])
        for name in sorted(set(grouped) | set(estimates) | set(catalog)):
            group, estimate, old = grouped.get(name, []), estimates.get(name), catalog.get(name)
            organizations = [estimate['Organization'] if estimate else '', old['organization'] if old else ''] + [r['organization'] for r in group]
            organization = next((v for v in organizations if v), '')
            lab = lab_for(organization)
            inferred = False
            if not organization:
                lab, inferred = family_lab(name), True
            if not lab:
                continue
            dates = sorted({r['date'] for r in group if re.fullmatch(r'\d{4}-\d{2}-\d{2}', r['date'])})
            recorded_date = estimate['date'] if estimate and estimate['date'] else dates[0] if dates else old['date'] if old else None
            if recorded_date:
                datetime.date.fromisoformat(recorded_date)
            score = number(estimate['eci']) if estimate else None
            lo = number(estimate['eci_ci_low']) if estimate else None
            hi = number(estimate['eci_ci_high']) if estimate else None
            if score is not None:
                assert (lo is None or lo <= score) and (hi is None or score <= hi)
            variants = sorted({r['model_version'] for r in group if r['model_version']})
            compute = next((number(r['training_compute_flop']) for r in group if r['training_compute_flop']), None)
            records[name] = {
                'id': name, 'name': estimate.get('Display name') or name if estimate else name,
                'lab': lab, 'organization': organization or None, 'lab_inferred': inferred,
                'date': recorded_date, 'date_basis': 'Benchmark release date' if estimate or dates else 'Catalog publication date',
                'catalog_date': old['date'] if old else None, 'catalog_releases': catalog_aliases.get(name, []),
                'eci': score, 'eci_low': lo, 'eci_high': hi,
                'access': estimate['Accessibility group'] or estimate['Model accessibility'] if estimate else old['access'] if old else next((r['accessibility'] for r in group if r['accessibility']), 'Not stated'),
                'domain': old['domain'] if old else None, 'parameters': old['parameters'] if old else None,
                'compute_flop': number(old['compute_flop']) if old and old['compute_flop'] else compute,
                'variants': variants, 'benchmarks': {},
                'catalog_link': old['link'] if old else None,
                'source': 'https://epoch.ai/benchmarks',
            }

        unmatched = defaultdict(int)
        for filename, label, domain in BENCHMARKS:
            for row in rows(filename):
                version = row['Model version']
                names = variant_groups.get(version, set())
                if len(names) != 1:
                    unmatched[filename] += 1
                    continue
                model = records.get(next(iter(names)))
                if not model:
                    continue
                score = number(row['Best score (across scorers)'])
                if score is None:
                    continue
                assert 0 <= score <= 1
                entry = model['benchmarks'].setdefault(filename, {'score': score * 100, 'variant': version, 'configurations': []})
                entry['configurations'].append({'variant': version, 'score': score * 100})
                if score * 100 > entry['score']:
                    entry['score'], entry['variant'] = score * 100, version

    result = {
        'fetched_on': fetched_on, 'source_url': 'https://epoch.ai/data/benchmark_data.zip',
        'zip_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'catalog_snapshot': json.loads(catalog_path.read_text())['source']['csv_sha256'],
        'license': 'CC BY 4.0; attribute Epoch AI', 'labs': list(LABS),
        'benchmarks': [{'id': f, 'name': n, 'domain': d} for f, n, d in BENCHMARKS],
        'unmatched_benchmark_rows': dict(unmatched),
        'models': sorted(records.values(), key=lambda r: (r['date'] or '', r['id']), reverse=True),
    }
    assert {'GPT-6 Astra', 'GPT-6.1 Sol', 'GPT-6.1 Terra', 'GPT-6 Luna'} <= set(records)
    expected_groups = {r['model_group'] for r in metadata if r['model_group'] and lab_for(r['organization'])}
    assert expected_groups <= set(records), 'A requested-lab source group was dropped'
    expected_catalog = {r['name'] for r in catalog_rows if lab_for(r['organization'])}
    preserved_catalog = {c['name'] for r in records.values() for c in r['catalog_releases']}
    assert expected_catalog <= preserved_catalog, 'An existing requested-lab release was dropped'
    assert any(r['eci'] is None for r in records.values()), 'Unscored models must remain visible'
    assert len(result['models']) == len(set(r['id'] for r in result['models']))
    assert all(r['eci'] is None or (r['eci_low'] is None or r['eci_low'] <= r['eci']) and (r['eci_high'] is None or r['eci'] <= r['eci_high']) for r in result['models'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='Private path to the Epoch benchmark_data.zip export')
    parser.add_argument('--catalog', type=Path, default=ROOT / 'data/models.json')
    parser.add_argument('--fetched-on', required=True, help='Export retrieval date (YYYY-MM-DD)')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/model-progress.json')
    args = parser.parse_args()
    result = build(args.archive, args.catalog, args.fetched_on)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    records = {row['id']: row for row in result['models']}
    unmatched = result['unmatched_benchmark_rows']
    print('Models', len(records), 'with ECI', sum(r['eci'] is not None for r in records.values()))
    print('By lab', {lab: sum(r['lab'] == lab for r in records.values()) for lab in LABS})
    print('Name-attributed labs', sum(r['lab_inferred'] for r in records.values()), 'unmatched benchmark rows', dict(unmatched))


if __name__ == '__main__':
    main()
