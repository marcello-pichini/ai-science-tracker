"""Build separate, attributed numerical benchmark snapshots from reviewed inputs.

Inputs and license notices are pinned in public-benchmark-inputs.json. Raw inputs
stay in work/. This importer does not scrape live leaderboards, join model names,
normalize unlike metrics, or copy benchmark questions, charts or trajectories.
"""
import argparse
import csv
import datetime
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import math
from pathlib import Path
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'scripts/public-benchmark-inputs.json'


def number(value, maximum=None):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean score')
    value = float(value)
    if not math.isfinite(value) or maximum is not None and not 0 <= value <= maximum:
        raise ValueError('Invalid score')
    return value


def clean(value):
    value = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', value)
    return html.unescape(re.sub('<[^>]*>', '', value)).strip()


def metr_yaml(content):
    """Read public METR numerical YAML, rejecting duplicate identities/fields."""
    import yaml
    if len(content) > 2000000:
        raise ValueError('Unexpected METR export size')
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError('Duplicate METR field or evaluation identity')
            result[key] = loader.construct_object(value_node, deep=deep)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(content, Loader=UniqueLoader)


class Tables(HTMLParser):
    """Read table cell text only; never execute downloaded source markup."""
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, text):
        if self.cell is not None:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def row(model, metric, value, unit, source_url, key, *, details=None,
        date=None, date_basis='Not reported', direction='Higher is better', group=None):
    value = number(value, 1 if unit == 'fraction' else 100 if unit == '%' else None)
    if value is None or not model or not metric:
        raise ValueError('Missing model, metric or score')
    if date:
        datetime.date.fromisoformat(date[:10])
    return {'id': hashlib.sha256(key.encode()).hexdigest()[:20], 'model': model,
            'metric': metric, 'value': value, 'unit': unit, 'direction': direction,
            'comparison_group': group or metric, 'date': date, 'date_basis': date_basis,
            'source_url': source_url, 'details': details or {}}


def parse_records(source_id, inputs, directory):
    def text(key):
        return (directory / inputs[key]['file']).read_text()

    def url(key):
        return inputs[key]['source_url']

    records = []
    if source_id == 'metr':
        for key, version in [('metr-th-1-1', 'METR-Horizon-v1.1'), ('metr-th-1-0', 'METR-Horizon-v1.0')]:
            data = metr_yaml(text(key))
            for field in ('license', 'license_url', 'licence'):
                if field in data and data[field] not in ('CC BY 4.0', 'cc-by-4.0', 'https://creativecommons.org/licenses/by/4.0/'):
                    raise ValueError('METR numerical export license requires review')
            if data.get('benchmark_name') != version or not 0 < len(data['results']) <= 2000:
                raise ValueError('METR evaluation version/schema changed')
            for alias, item in data['results'].items():
                if version == 'METR-Horizon-v1.1' and item.get('benchmark_name') == 'METR-Horizon-v1.0':
                    baseline = metr_yaml(text('metr-th-1-0'))['results'].get(alias)
                    if baseline != item:
                        raise ValueError('Conflicting inherited METR v1.0 baseline')
                    # The v1.1 export stitches in identical old baselines. Keep
                    # them once under their actual v1.0 suite, never as reruns.
                    continue
                if item.get('benchmark_name') != version or not isinstance(alias, str):
                    raise ValueError('METR row version or identity mismatch')
                date = item.get('release_date')
                date = date.isoformat() if isinstance(date, datetime.date) else date
                for probability, field in [(50, 'p50_horizon_length'), (80, 'p80_horizon_length')]:
                    estimate = item['metrics'][field]
                    value = number(estimate.get('estimate'))
                    if value is None:
                        continue
                    low, high = number(estimate.get('ci_low')), number(estimate.get('ci_high'))
                    if value < 0 or any(v is not None and v < 0 for v in (low, high)) or low is not None and high is not None and low > high:
                        raise ValueError('Invalid METR horizon or interval')
                    metric = version + ' · ' + str(probability) + '% success horizon'
                    result = row(alias, metric, value, 'human-baseline minutes', url(key),
                        version + ':' + alias + ':' + str(probability), date=date,
                        date_basis='Source model release date; evaluation date not reported',
                        direction='Longer task duration at this success threshold',
                        details={'evaluation_version': version, 'success_threshold_percent': probability,
                            'source_alias': alias, 'scaffolds': item.get('scaffolds'),
                            'long_tasks_version': data.get('long_tasks_version'),
                            'swaa_version': data.get('swaa_version')})
                    result['interval'] = {'low': low, 'high': high, 'level_percent': 95,
                        'method': 'METR-reported bootstrapped confidence interval', 'unit': 'human-baseline minutes'}
                    result['caution'] = 'Above 16 hours: METR says measurements are unreliable with this task suite.' if value > 960 else None
                    records.append(result)
    elif source_id == 'gpqa':
        with zipfile.ZipFile(directory / inputs['epoch-zip']['file']) as archive:
            names = [n for n in archive.namelist() if n.split('/')[-1] == 'gpqa_diamond.csv']
            if len(names) != 1:
                raise ValueError('Expected own-run GPQA Diamond CSV only')
            rows = csv.DictReader(io.StringIO(archive.read(names[0]).decode('utf-8-sig')))
            for item in rows:
                if item['mean_score'] == '':
                    continue
                records.append(row(item['Model version'], 'Mean accuracy', item['mean_score'],
                    'fraction', 'https://epoch.ai/benchmarks/gpqa-diamond', item['id'],
                    date=item['Started at'][:10] or None, date_basis='Evaluation start',
                    details={k: item[k] for k in ['Model version', 'Organization', 'stderr',
                        'Release date', 'Started at', 'Best score (across scorers)', 'id', 'Log viewer', 'Logs']}))
    elif source_id == 'arena':
        if 'arena-parquet' in inputs:
            import pyarrow.parquet as parquet
            table = parquet.read_table(io.BytesIO((directory / inputs['arena-parquet']['file']).read_bytes()), use_threads=False)
            if not 0 < table.num_rows <= 200000:
                raise ValueError('Unexpected Arena row count')
            entries = [{'row_idx': index, 'row': item} for index, item in enumerate(table.to_pylist())]
        else:
            pages = [json.loads(text(k)) for k in inputs if k.startswith('arena-page-')]
            if not pages or len({p['num_rows_total'] for p in pages}) != 1:
                raise ValueError('Missing or inconsistent Arena pages')
            entries = [r for p in pages for r in p['rows']]
            expected = pages[0]['num_rows_total']
            if len(entries) != expected or {r['row_idx'] for r in entries} != set(range(expected)):
                raise ValueError('Incomplete or duplicated Arena pagination')
        for entry in entries:
            item = entry['row']
            if item['category'] != 'overall':
                continue
            records.append(row(item['model_name'], 'Text Arena rating · overall', item['rating'],
                'rating points', url('arena-parquet') if 'arena-parquet' in inputs else url('arena-card'), str(entry['row_idx']),
                date=item['leaderboard_publish_date'], date_basis='Leaderboard publication',
                details={k: item[k] for k in ['organization', 'rating_lower', 'rating_upper',
                    'variance', 'vote_count', 'rank', 'category', 'license']}))
    elif source_id == 'tau':
        manifest = json.loads(text('tau-manifest'))
        for name in manifest['submissions']:
            key = 'tau-' + name
            item = json.loads(text(key))
            method = item.get('methodology') or {}
            version = method.get('tau2_bench_version') or 'Version not reported'
            for domain, result in item['results'].items():
                if not isinstance(result, dict) or result.get('pass_1') is None:
                    continue
                metric = 'Pass^1 · ' + domain
                group = ' · '.join([metric, version, str(result.get('retrieval_config', 'default retrieval')),
                                     str(method.get('user_simulator', 'Simulator not reported'))])
                # Explicit allowlist: never republish contact_info or trajectories.
                details = {k: item.get(k) for k in ['model_organization', 'submitting_organization',
                    'submission_date', 'reasoning_effort', 'submission_type']}
                details.update({'methodology': method, 'domain_results': result,
                                'source_submission': name, 'modality': item.get('modality', 'text')})
                records.append(row(item['model_name'], metric, result['pass_1'], '%', url(key),
                    name + ':' + domain, date=method.get('evaluation_date') or item.get('submission_date'),
                    date_basis='Evaluation date, or submission date if absent', details=details, group=group))
    elif source_id == 'chembench':
        for key, label in [('chembench-gpt4o', 'gpt-4o'), ('chembench-claude35', 'claude3.5')]:
            item = json.loads(text(key))
            records.append(row(label, 'Fraction correct · legacy report', item['fraction_correct'],
                'fraction', url(key), key, details={'source_label': label,
                    'scope': 'Legacy repository report; exact release date not stated. Question-level outputs omitted.'}))
    elif source_id == 'bixbench':
        for label, item in json.loads(text('bixbench')).items():
            records.append(row(label, 'Zero-shot accuracy · v1.5', item['accuracy'], 'fraction',
                url('bixbench'), label, details=item,
                group='v1.5 · zero-shot · ' + label.split('-grader-')[1]))
    elif source_id == 'mmlu-pro':
        for line in text('mmlu-pro').splitlines():
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if len(cells) == 2 and re.fullmatch(r'\d+\.\d+', cells[1]):
                records.append(row(cells[0], 'Overall accuracy · README snapshot', cells[1], '%',
                    url('mmlu-pro'), cells[0], details={'scope': 'Historical README mini-leaderboard; evaluation date not reported.'}))
    elif source_id == 'charxiv':
        for key in inputs:
            if not key.startswith('charxiv-stats-'):
                continue
            item = json.loads(text(key))
            label, split = key.removeprefix('charxiv-stats-').rsplit('-', 1)
            records.append(row(label, item['Question Type'] + ' · validation overall',
                item['Overall Score'], '%', url(key), key, details=item))
    elif source_id == 'ruler':
        for line in text('ruler').splitlines():
            if not line.lstrip('|').startswith('['):
                continue
            cells = line.strip().strip('|').split('|')
            if len(cells) < 4:
                continue
            label = clean(cells[0])
            for index, length in enumerate(['4K', '8K', '16K', '32K', '64K', '128K'], 3):
                if index >= len(cells):
                    continue
                score = clean(cells[index])
                if not re.fullmatch(r'\d+(?:\.\d+)?', score):
                    continue
                records.append(row(label, 'Accuracy · ' + length + ' context', score, '%',
                    url('ruler'), label + ':' + length, details={'claimed_length': clean(cells[1]),
                        'effective_length': clean(cells[2]), 'context_length': length,
                        'scope': 'README snapshot includes source-reported author results; asterisk and model size retained in label. See source notes for protocol exceptions.'}))
    elif source_id == 'agentdojo':
        table = Tables()
        table.feed(text('agentdojo'))
        for index, cells in enumerate(table.rows[1:]):
            if len(cells) != 9:
                raise ValueError('AgentDojo table schema changed')
            for column, metric, direction in [(4, 'Utility', 'Higher is better'),
                    (5, 'Utility under attack', 'Higher is better'), (6, 'Targeted attack success', 'Lower is better')]:
                if cells[column] in ('', '-', 'N/A'):
                    continue
                records.append(row(cells[1], metric, cells[column].rstrip('%'), '%',
                    url('agentdojo'), str(index) + ':' + metric, date=cells[7], date_basis='Source table date',
                    direction=direction, group=metric + ' · defense ' + cells[2] + ' · attack ' + cells[3],
                    details={'provider': cells[0], 'defense': cells[2], 'attack': cells[3]}))
    elif source_id == 'swe-bench-pro':
        table = Tables()
        table.feed(text('swe-bench-pro'))
        for cells in table.rows[1:]:
            if len(cells) != 4:
                raise ValueError('SWE-bench Pro table schema changed')
            records.append(row(cells[0], 'Resolved · initial 730-problem runs', cells[1], '%',
                url('swe-bench-pro'), cells[0], details={'agent': 'SWE-Agent', 'problems': 730,
                    'turn_limit': 250, 'cost_cap': 'Uncapped', 'status': 'Initial runs; source warns results may change. Not SWE-bench Verified.'}))
    else:
        raise ValueError('Unreviewed source ' + source_id)
    if not records or len({r['id'] for r in records}) != len(records):
        raise ValueError('Empty or duplicate numerical records for ' + source_id)
    return records


def build_component(source, manifest, directory):
    """Build one component without requiring raw inputs for unrelated sources."""
    available = {r['id']: r for r in manifest['inputs']}
    if not set(source['inputs']) <= set(available):
        raise ValueError('Missing component inputs')
    inputs = {key: available[key] for key in source['inputs']}
    for item in inputs.values():
        if hashlib.sha256((directory / item['file']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Unreviewed input bytes: ' + item['id'])
    notice = ROOT / source['license_notice']
    expected = [inputs[k]['sha256'] for k in source['inputs']
                if k.endswith('-license') or k in ('cc-by-4.0', 'cc-by-sa-4.0')]
    if not source.get('attribution') or hashlib.sha256(notice.read_bytes()).hexdigest() not in expected:
        raise ValueError('Missing attribution or modified license notice: ' + source['id'])
    records = parse_records(source['id'], inputs, directory)
    serialized = json.dumps(records, ensure_ascii=False, allow_nan=False)
    if re.search(r'"(?:contact_info|email|messages|trajectory_files)"|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', serialized):
        raise ValueError('Unexpected contact or trajectory content in numerical component')
    return {**source, 'schema_version': 1, 'retrieved_on': source.get('retrieved_on', manifest['retrieved_on']),
            'changes': 'Selected numerical results; fields renamed and evaluation slices labeled. Original numerical scales retained. Questions, paper images, transcripts, contacts and trajectories excluded.',
            'records': records, 'input_sha256': {key: inputs[key]['sha256'] for key in source['inputs']}}


def build(manifest, directory, output):
    inputs = {r['id']: r for r in manifest['inputs']}
    for item in inputs.values():
        path = directory / item['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Unreviewed input bytes: ' + item['id'])
    output.mkdir(parents=True, exist_ok=True)
    registry = {'schema_version': 1, 'retrieved_on': manifest['retrieved_on'],
        'scope': 'Separate numerical source snapshots. No composite ranking or inferred model joins.',
        'reuse': 'Each component retains its own license; no blanket catalog license applies.',
        'sources': []}
    for source in manifest['sources']:
        result = build_component(source, manifest, directory)
        path = output / (source['id'] + '.json')
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        path.write_text(payload)
        registry['sources'].append({k: v for k, v in source.items() if k != 'inputs'} | {
            'path': 'data/benchmarks/' + path.name, 'record_count': len(result['records']),
            'sha256': hashlib.sha256(payload.encode()).hexdigest()})
    (output / 'index.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n')
    return registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=ROOT / 'work/metric-enrichment')
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/benchmarks')
    parser.add_argument('--download', action='store_true', help='Fetch pinned inputs; hash mismatches stop the import')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.download:
        args.inputs.mkdir(parents=True, exist_ok=True)
        for item in manifest['inputs']:
            path = args.inputs / item['file']
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']:
                continue
            with urllib.request.urlopen(item['download_url'], timeout=30) as response:
                content = response.read()
            if item.get('normalization') == 'canonical-json':
                content = json.dumps(json.loads(content), sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()
            if hashlib.sha256(content).hexdigest() != item['sha256']:
                raise ValueError('Source changed or unavailable; review required: ' + item['id'])
            path.write_bytes(content)
    registry = build(manifest, args.inputs, args.output)
    for source in registry['sources']:
        print(source['id'], source['record_count'], source['license'])


if __name__ == '__main__':
    main()
