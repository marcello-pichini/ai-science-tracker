"""Select verified Pages deployments and isolate refresh sources."""
import argparse
import datetime as dt
import json
import hashlib
import os
from pathlib import Path
import subprocess


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def select(repository, require_check=False, require_current=False, fetch=api):
    prefix = 'repos/' + repository
    main = fetch(prefix + '/commits/main')
    deployed = None
    for deployment in fetch(prefix + '/deployments?environment=github-pages&per_page=100'):
        statuses = fetch(prefix + '/deployments/' + str(deployment['id']) + '/statuses?per_page=100')
        if statuses and statuses[0]['state'] == 'success':
            deployed = deployment
            break
    if deployed is None:
        raise RuntimeError('No successful current github-pages deployment found')
    sha = deployed['sha']
    if require_current and sha != main['sha']:
        raise RuntimeError('Current main has not successfully deployed')
    if require_check:
        runs = fetch(prefix + '/actions/workflows/check.yml/runs?head_sha=' + sha + '&per_page=100')['workflow_runs']
        valid = [r for r in runs if r['head_sha'] == sha and r['head_branch'] == 'main'
                 and r['event'] in ('push', 'workflow_dispatch')
                 and r['head_repository']['full_name'] == repository]
        if not valid or valid[0]['conclusion'] != 'success':
            raise RuntimeError('Latest trusted exact-SHA Check did not succeed')
    return {'expected_sha': main['sha'], 'deployed_sha': sha,
            'expected_updated_at': main['commit']['committer']['date'],
            'grace_seconds': 7200, 'deployment_id': deployed['id']}


def source_transaction(root, name, paths, command):
    originals = {p: (root / p).read_bytes() if (root / p).exists() else None for p in paths}
    try:
        subprocess.run(command, cwd=root, check=True)
        return {'id': name, 'status': 'updated' if any((root / p).read_bytes() != old for p, old in originals.items()) else 'unchanged'}
    except (subprocess.CalledProcessError, OSError) as error:
        for path, content in originals.items():
            target = root / path
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
        return {'id': name, 'status': 'held', 'reason': str(error)}


def refresh(root):
    date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    work = root / 'work'
    work.mkdir(exist_ok=True)
    rows = []
    sources = [
        ('epoch-models', ['data/models.json'], 'https://epoch.ai/data/notable_ai_models.csv', 'work/epoch/notable_ai_models.csv', ['python3', 'scripts/generate_models.py']),
        ('epoch-progress', ['data/model-progress.json'], 'https://epoch.ai/data/benchmark_data.zip', 'work/epoch/benchmark_data.zip', ['python3', 'scripts/import_model_progress.py', 'work/epoch/benchmark_data.zip', '--fetched-on', date, '--refresh-if-changed']),
        ('swe-bench', ['data/swe-bench.json'], 'https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json', 'work/swe-bench/leaderboards.json', ['python3', 'scripts/import_swe_bench.py', 'work/swe-bench/leaderboards.json', '--fetched-on', date]),
    ]
    models_path = root / 'data/models.json'
    previous_models = models_path.read_bytes()
    for name, paths, url, destination, generator in sources:
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        result = subprocess.run(['curl', '-fsSL', '--retry', '3', '-o', str(target), url])
        if result.returncode:
            target.unlink(missing_ok=True)
            rows.append({'id': name, 'status': 'held', 'reason': 'download failed'})
            continue
        if name == 'epoch-models':
            previous = json.loads(previous_models)
            old_hash = previous.get('source', {}).get('csv_sha256')
            if old_hash and hashlib.sha256(target.read_bytes()).hexdigest() == old_hash:
                rows.append({'id': name, 'status': 'unchanged'})
                continue
        rows.append(source_transaction(root, name, paths, generator))
    models_result, progress_result = rows[:2]
    if models_result['status'] == 'updated' and progress_result['status'] == 'held':
        models_path.write_bytes(previous_models)
        models_result.update(status='held', reason='Matching Epoch progress refresh failed')
    command = ['bash', '-c', 'python3 -m pip install -r scripts/requirements-benchmarks.txt && python3 scripts/refresh_public_benchmarks.py "$@"', 'benchmark-refresh']
    epoch_zip = root / 'work/epoch/benchmark_data.zip'
    if epoch_zip.exists():
        command += ['--epoch-zip', str(epoch_zip)]
    paths = ['scripts/public-benchmark-inputs.json'] + [str(p.relative_to(root)) for p in (root / 'data/benchmarks').glob('*.json')]
    rows.append(source_transaction(root, 'independent-benchmarks', paths, command))
    benchmark_report = work / 'benchmark-refresh-report.json'
    if benchmark_report.exists():
        rows.extend(json.loads(benchmark_report.read_text())['sources'])
    report = {'checked_on': date, 'sources': rows, 'complete': all(row['status'] != 'held' for row in rows)}
    (work / 'source-refresh-report.json').write_text(json.dumps(report, indent=2) + '\n')
    for row in rows:
        if row['status'] == 'held':
            print('::warning::Source ' + row['id'] + ' failed; retained previous snapshot')
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['select', 'refresh'])
    parser.add_argument('--require-check', action='store_true')
    parser.add_argument('--require-current', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'refresh':
        refresh(Path.cwd())
    else:
        result = select(os.environ['GITHUB_REPOSITORY'], args.require_check, args.require_current)
        args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
