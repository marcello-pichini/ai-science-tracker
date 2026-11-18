"""Refresh the licensed numerical selections, retaining blocked components.

Only reviewed repositories, file selections and licenses are eligible. An
upstream license/NOTICE change, unsupported protocol or malformed score holds
that component and emits a visible report; other valid updates can proceed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request

import import_public_benchmarks as importer

ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = {
    'tau': ('sierra-research/tau2-bench', 'main'),
    'chembench': ('lamalab-org/chembench', 'dev'),
    'bixbench': ('Future-House/BixBench', 'main'),
    'mmlu-pro': ('TIGER-AI-Lab/MMLU-Pro', 'main'),
    'ruler': ('NVIDIA/RULER', 'main'),
    'agentdojo': ('ethz-spylab/agentdojo', 'main'),
    'swe-bench-pro': ('scaleapi/SWE-bench_Pro-os', 'main'),
}


def fetch(url):
    headers = {'User-Agent': 'AI-Science-Tracker benchmark-refresh'}
    if url.startswith('https://api.github.com/') and os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
        return response.read()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def canonical(content):
    return json.dumps(json.loads(content), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def semantic(result):
    # A new unrelated repository commit is not a new numerical snapshot.
    records = [{k: v for k, v in r.items() if k != 'source_url'} for r in result['records']]
    return {'records': records, 'license': result['license'], 'attribution': result['attribution'],
            'scope': result['scope'], 'selection': result['selection'], 'maintenance': result['maintenance'],
            'source_status': result.get('source_status')}


def prepare(source, manifest, directory, epoch_zip=None):
    """Fetch one eligible selection, validating rights before accepting new rows."""
    source = copy.deepcopy(source)
    old_inputs = {i['id']: i for i in manifest['inputs']}
    selected = {key: copy.deepcopy(old_inputs[key]) for key in source['inputs']}
    content = {}
    source_id = source['id']
    hf_meta = None
    if source_id in REPOSITORIES:
        repo, branch = REPOSITORIES[source_id]
        head = json.loads(fetch(f'https://api.github.com/repos/{repo}/git/ref/heads/{branch}'))['object']['sha']
        if not re.fullmatch('[0-9a-f]{40}', head):
            raise ValueError('Invalid upstream revision')
        tree = json.loads(fetch(f'https://api.github.com/repos/{repo}/git/trees/{head}'))['tree']
        if any(re.fullmatch(r'NOTICE(?:\..*)?', f['path'], re.I) for f in tree):
            raise ValueError('Upstream NOTICE requires review')
        for item in selected.values():
            item['download_url'] = item['download_url'].replace(source['upstream_revision'], head)
            item['source_url'] = item['source_url'].replace(source['upstream_revision'], head)
        source['license_url'] = source['license_url'].replace(source['upstream_revision'], head)
        source['upstream_revision'] = head
    elif source_id in ('arena', 'charxiv'):
        repo = 'lmarena-ai/leaderboard-dataset' if source_id == 'arena' else 'princeton-nlp/CharXiv'
        hf_meta = json.loads(fetch('https://huggingface.co/api/datasets/' + repo))
        expected = 'cc-by-4.0' if source_id == 'arena' else 'cc-by-sa-4.0'
        if hf_meta.get('cardData', {}).get('license') != expected:
            raise ValueError('Numerical dataset license changed or missing')
        revision = hf_meta['sha']
        for item in selected.values():
            item['download_url'] = item['download_url'].replace(source['upstream_revision'], revision)
            item['source_url'] = item['source_url'].replace(source['upstream_revision'], revision)
        source['upstream_revision'] = revision
        if source_id == 'charxiv':
            license_repo = 'princeton-nlp/CharXiv'
            license_head = json.loads(fetch(f'https://api.github.com/repos/{license_repo}/git/ref/heads/main'))['object']['sha']
            license_tree = json.loads(fetch(f'https://api.github.com/repos/{license_repo}/git/trees/{license_head}'))['tree']
            if any(re.fullmatch(r'NOTICE(?:\..*)?', f['path'], re.I) for f in license_tree):
                raise ValueError('CharXiv NOTICE requires review')
            selected['charxiv-data-license']['download_url'] = f'https://raw.githubusercontent.com/{license_repo}/{license_head}/data/LICENSE'
            selected['charxiv-data-license']['source_url'] = selected['charxiv-data-license']['download_url']

    # Retain exact approved legal text. Never auto-accept a new license notice.
    legal_keys = [k for k in selected if k.endswith('-license') or k in ('cc-by-4.0', 'cc-by-sa-4.0')]
    for key in legal_keys:
        body = fetch(selected[key]['download_url'])
        if hashlib.sha256(body).hexdigest() != old_inputs[key]['sha256']:
            raise ValueError('License text changed; explicit source review required')
        content[key] = body

    if source_id == 'metr':
        if source.get('permission_confirmed_on') != '2026-11-18' or source['license'] != 'CC BY 4.0':
            raise ValueError('METR public-data permission requires review')
        expected = {
            'metr-th-1-1': 'https://metr.org/assets/benchmark_results_1_1.yaml',
            'metr-th-1-0': 'https://metr.org/assets/benchmark_results_1_0.yaml',
            'metr-source-page': 'https://metr.org/time-horizons/',
        }
        if any(selected[k]['download_url'] != url for k, url in expected.items()):
            raise ValueError('METR endpoint expansion requires review')
        content['metr-source-page'] = fetch(expected['metr-source-page'])
        page = content['metr-source-page'].decode()
        if 'time horizon' not in page.lower() or '16 hrs' not in page or '95% CI' not in page:
            raise ValueError('METR units, interval or saturation policy needs review')
        if re.search(r'CC\s*BY[- ]NC|CC\s*BY[- ]ND|not permitted to (?:reuse|redistribute)', page, re.I):
            raise ValueError('METR public-page reuse terms need review')
        update = re.search(r'class="post-date"[^>]*>([^<]+)</', page)
        source['source_status'] = {
            'actively_updated': 'no longer actively updated' not in page,
            'page_last_updated': datetime.datetime.strptime(update[1].strip(), '%B %d, %Y').date().isoformat() if update else None,
        }
        state = 'METR states the source page is no longer actively updated.' if not source['source_status']['actively_updated'] else 'Source maintenance notice checked.'
        source['maintenance'] = 'Checked daily for changes to these public exports; blocked sources retain the last accepted snapshot. ' + state
    elif source_id == 'gpqa':
        # The own-run license is scoped by Epoch's reuse page, not the ZIP alone.
        policy = fetch('https://epoch.ai/benchmarks/use-this-data').decode()
        if 'creativecommons.org/licenses/by/' not in policy or 'retains its original licensing' not in policy:
            raise ValueError('Epoch reuse policy needs review')
        content['epoch-zip'] = epoch_zip.read_bytes() if epoch_zip else fetch(selected['epoch-zip']['download_url'])
    elif source_id == 'arena':
        selected = {k: v for k, v in selected.items() if not k.startswith('arena-page-')}
        url = 'https://huggingface.co/datasets/' + repo + '/resolve/' + source['upstream_revision'] + '/text/latest-00000-of-00001.parquet'
        selected['arena-parquet'] = {'id': 'arena-parquet', 'file': 'arena-text-latest.parquet',
                                    'download_url': url, 'source_url': url}
    elif source_id == 'tau':
        content['tau-manifest'] = fetch(selected['tau-manifest']['download_url'])
        names = json.loads(content['tau-manifest'])['submissions']
        if not names or len(names) > 1000 or any(not re.fullmatch('[A-Za-z0-9_.-]+', n) for n in names):
            raise ValueError('Unexpected text submission manifest')
        selected = {k: v for k, v in selected.items() if not k.startswith('tau-') or k == 'tau-manifest'}
        for name in names:
            key = 'tau-' + name
            url = f'https://raw.githubusercontent.com/{repo}/{head}/web/leaderboard/public/submissions/{name}/submission.json'
            selected[key] = {'id': key, 'file': key + '.raw', 'download_url': url, 'source_url': url}
    elif source_id == 'charxiv':
        selected = {k: v for k, v in selected.items() if not k.startswith('charxiv-stats-')}
        for item in hf_meta['siblings']:
            path = item['rfilename']
            if not re.fullmatch(r'existing_evaluations/stats-[A-Za-z0-9_.-]+-(?:descriptive|reasoning)_val.json', path):
                continue
            key = 'charxiv-' + path.split('/')[-1].removesuffix('.json')
            url = 'https://huggingface.co/datasets/' + repo + '/resolve/' + revision + '/' + path
            selected[key] = {'id': key, 'file': key + '.raw', 'download_url': url, 'source_url': url}
        if not any(k.startswith('charxiv-stats-') for k in selected):
            raise ValueError('No supported CharXiv aggregate files')

    def retrieve(key):
        return key, fetch(selected[key]['download_url'])
    with ThreadPoolExecutor(max_workers=8) as pool:
        content.update(pool.map(retrieve, [k for k in selected if k not in content]))
    if hf_meta:
        after = json.loads(fetch('https://huggingface.co/api/datasets/' + repo))
        if after['sha'] != hf_meta['sha']:
            raise ValueError('Dataset changed during retrieval')
    if source_id == 'swe-bench-pro':
        text = content['swe-bench-pro'].decode()
        if not all(term in text for term in ['730', 'uncapped cost', 'turn limit of 250', 'initial runs']):
            raise ValueError('SWE-bench Pro selected protocol changed')
    if source_id == 'ruler' and not all(x in content['ruler'].decode() for x in ['Claimed Length', 'Effective Length', '|4K|8K|16K|32K|64K|128K|']):
        raise ValueError('RULER selected protocol changed')
    source['inputs'] = list(selected)
    first_key = 'arena-card' if source_id == 'arena' else source['inputs'][0]
    source['source_url'] = selected[first_key]['source_url']
    for key, body in content.items():
        item = selected[key]
        item['sha256'] = hashlib.sha256(body).hexdigest()
        (directory / item['file']).write_bytes(body)
    return source, list(selected.values())


def refresh(root, manifest_path, output, checked_on, epoch_zip=None):
    datetime.date.fromisoformat(checked_on)
    manifest = json.loads(manifest_path.read_text())
    report = {'checked_on': checked_on, 'sources': []}
    accepted = {}
    with tempfile.TemporaryDirectory(prefix='benchmark-refresh-') as tmp:
        cache = Path(tmp)
        for original in manifest['sources']:
            sid = original['id']
            try:
                source, inputs = prepare(original, manifest, cache, epoch_zip)
                source['retrieved_on'] = checked_on
                candidate = importer.build_component(source, {'inputs': inputs, 'retrieved_on': checked_on}, cache)
                previous = json.loads((output / (sid + '.json')).read_text())
                if semantic(candidate) == semantic(previous):
                    report['sources'].append({'id': sid, 'status': 'unchanged'})
                    continue
                # Preserve the last accepted snapshot if this source fails; no
                # raw input, report or failed candidate enters public exports.
                accepted[sid] = (source, inputs, candidate)
                report['sources'].append({'id': sid, 'status': 'updated', 'records': len(candidate['records'])})
            except Exception as error:
                report['sources'].append({'id': sid, 'status': 'held', 'reason': str(error)[:300]})
    if accepted:
        for sid, (source, inputs, candidate) in accepted.items():
            (output / (sid + '.json')).write_bytes(encode(candidate))
        manifest['sources'] = [accepted[s['id']][0] if s['id'] in accepted else s for s in manifest['sources']]
        replacements = {i['id']: i for _, inputs, _ in accepted.values() for i in inputs}
        kept = {k for s in manifest['sources'] for k in s['inputs']}
        all_inputs = {i['id']: i for i in manifest['inputs']}
        all_inputs.update(replacements)
        manifest['inputs'] = [i for k, i in all_inputs.items() if k in kept]
        manifest['retrieved_on'] = max([checked_on, manifest['retrieved_on']])
        manifest_path.write_bytes(encode(manifest))
        registry = json.loads((output / 'index.json').read_text())
        registry['retrieved_on'] = manifest['retrieved_on']
        registry['sources'] = []
        for source in manifest['sources']:
            path = output / (source['id'] + '.json')
            data = json.loads(path.read_text())
            registry['sources'].append({k: v for k, v in source.items() if k != 'inputs'} | {
                'path': 'data/benchmarks/' + path.name, 'record_count': len(data['records']),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        (output / 'index.json').write_bytes(encode(registry))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--checked-on', default=datetime.datetime.now(datetime.timezone.utc).date().isoformat())
    parser.add_argument('--epoch-zip', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT / 'work/benchmark-refresh-report.json')
    args = parser.parse_args()
    importer.ROOT = args.root
    report = refresh(args.root, args.root / 'scripts/public-benchmark-inputs.json',
                     args.root / 'data/benchmarks', args.checked_on, args.epoch_zip)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(encode(report))
    lines = ['## Independent benchmark refresh', '', '| Source | Result |', '| --- | --- |']
    for item in report['sources']:
        lines.append('| ' + item['id'] + ' | ' + item['status'] + ' |')
        if item['status'] == 'held':
            print('::warning::Benchmark ' + item['id'] + ' retained its previous snapshot: ' + item['reason'].replace('\n', ' '))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('\n'.join(lines) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
