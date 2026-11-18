"""Incremental cursors per source in work/harvest-state.json (not committed)."""
import json
import os
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "work" / "harvest-state.json"


def load(path=PATH):
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def save(state, path=PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, path)


def write_leads(rows, path):
    """Replace atomically; checkpoint cursors only after this durable candidate snapshot."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    os.replace(tmp, path)


def job_key(out, sources, job_id=None):
    """Logical identity remains stable when a checkpoint bundle changes directories."""
    if job_id:
        return 'job:' + job_id
    return 'output:' + Path(out).name + '|sources:' + ','.join(sorted(sources))


def get_job(snapshot, out, sources, job_id=None):
    jobs = snapshot.setdefault('jobs', {})
    key = job_key(out, sources, job_id)
    legacy = str(Path(out).resolve())
    if key not in jobs and legacy in jobs:
        jobs[key] = jobs.pop(legacy)
    return jobs.setdefault(key, {})


def collect_sources(adapters, window, out, checkpoint, budget=None, job_id=None):
    """Page cursors are committed after leads, so interrupted pages replay safely."""
    import inspect
    snapshot = load(checkpoint)
    job = get_job(snapshot, out, adapters, job_id)
    if job and not Path(out).exists() and any(r.get('retrieved', 0) for r in job.get('sources', {}).values()):
        raise ValueError('checkpoint requires its lead output; restore both files before resuming')
    if job and job.get('window') != window:
        raise ValueError('output/checkpoint window mismatch; choose a separate --out')
    job['window'] = window
    reports = job.setdefault('sources', {})
    rows = {}
    if Path(out).exists():
        for line in Path(out).read_text().splitlines():
            row = json.loads(line)
            rows[row['key']] = row

    def persist():
        write_leads(rows.values(), out)
        save(snapshot, checkpoint)

    for name, adapter in adapters.items():
        report = reports.setdefault(name, {'window': window, 'status': 'pending', 'retrieved': 0, 'coverage': 'selected adapter query only; not universal source coverage'})
        if report['status'] == 'complete':
            continue
        report['status'] = 'running'
        report.pop('error', None)
        try:
            supported = inspect.signature(adapter).parameters
            options = {k: v for k, v in {'report': report, 'checkpoint': persist, 'budget': budget}.items() if k in supported}
            for row in adapter(**options):
                rows[row['key']] = row
                report['retrieved'] += 1
                # Save each yielded row before asking the adapter to advance its cursor.
                write_leads(rows.values(), out)
            if report['status'] == 'running':
                report['status'] = 'incomplete'
                report['coverage'] = 'adapter does not establish exhaustive coverage'
        except Exception as error:
            report['status'] = 'error'
            report['error'] = f'{type(error).__name__}: {error}'
        if report.get('date_filter_applied') is False:
            report.pop('completed_window', None)
        elif report['status'] == 'complete':
            report['completed_window'] = window
        persist()
    job['status'] = 'complete' if all(reports[n]['status'] == 'complete' for n in adapters) else 'incomplete'
    persist()
    save(job, str(out) + '.coverage.json')
    return list(rows.values()), job
