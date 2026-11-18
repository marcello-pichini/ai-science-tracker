#!/usr/bin/env python3
"""Vulnerability harvest: run adapters, dedupe against the catalog, write leads, optionally backtest.

  python3 scripts/harvest/run_vuln.py --sources cvelist_delta,osv,mozilla,labs [--days 1] [--cleanup]
  python3 scripts/harvest/run_vuln.py --backtest [--since 2026-09-01] --sources osv,mozilla,labs,cvelist
Leads go to work/harvest/leads/<date>/vuln.jsonl (not committed). Raw downloads are deleted with --cleanup.
"""
import argparse
import collections
import json
import sys
import time
import datetime as dt
import functools
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harvest import fetch, known as kn, vuln, state  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def incremental_delta(since, until, known, report, checkpoint, budget=None):
    """Freeze delta IDs before fetching records; individual failed records remain resumable."""
    if 'ids' not in report:
        log = fetch.get_json(f"{vuln.CVE_RAW}/deltaLog.json", max_bytes=200 * 1024 ** 2)
        times = [entry['fetchTime'][:19] for entry in log]
        if not times or min(times) > since[:19]:
            raise RuntimeError('delta log does not cover requested start; backfill required')
        report['ids'] = sorted({item['cveId'] for entry in log
                                if since[:19] <= entry['fetchTime'][:19] <= until[:19]
                                for field in ('new', 'updated') for item in entry.get(field, [])})
        checkpoint()
    offset = report.get('cursor', 0)
    used = 0
    while offset < len(report['ids']):
        if budget and used >= budget:
            report['status'] = 'incomplete'
            return
        ident = report['ids'][offset]
        if not known.vuln(ident):
            row = vuln.from_cve_record(fetch.get_json(vuln.cve_url(ident)))
            if row:
                yield row
        offset += 1
        used += 1
        report['cursor'] = offset
        checkpoint()
    report['status'] = 'complete'


def incremental_osv(known, report, checkpoint, budget=None):
    report.update(scan_mode='current_snapshot', date_filter_applied=False,
                  date_basis='OSV published metadata retained; full ecosystem snapshot is not date-window coverage')
    offset = report.get('cursor', 0)
    used = 0
    while offset < len(vuln.OSV_ECOSYSTEMS):
        if budget and used >= budget:
            report['status'] = 'incomplete'
            return
        # Stream archive records so a malformed later record cannot discard earlier leads.
        import zipfile
        eco = vuln.OSV_ECOSYSTEMS[offset]
        path = fetch.download(f"https://osv-vulnerabilities.storage.googleapis.com/{eco.replace(' ', '%20')}/all.zip", f"osv-{eco}")
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith('.json'):
                    row = vuln.osv_entry(json.loads(archive.read(name)))
                    if row and not known.vuln(*row['ids']):
                        yield row
        offset += 1
        used += 1
        report['cursor'] = offset
        checkpoint()
    report['status'] = 'complete'


def complete_mozilla(known, report, checkpoint, budget=None):
    report.update(scan_mode='current_snapshot', date_filter_applied=False,
                  date_basis='current ai-involved bugs and advisory archive; lead dates may be unknown, no date-window filter')
    yield from vuln.iter_mozilla(known)
    report['status'] = 'complete'


def index_adapter(name, known, report, checkpoint, budget=None):
    yield from vuln.lab_index(name, known)
    report['status'] = 'incomplete'
    report['coverage'] = 'current lab index only; historical completeness not established'


def run(sources, days, k):
    out = {}
    for s in sources:
        t0 = time.time()
        if s == "cvelist_delta":
            out[s] = vuln.cvelist_delta(days, k)
        elif s == "osv":
            out[s] = vuln.osv(known=k)
        elif s == "mozilla":
            out[s] = vuln.mozilla(k)
        elif s == "labs":
            out[s] = [x for n in vuln.LAB_INDEXES for x in vuln.lab_index(n, k)]
        else:
            raise SystemExit(f"unknown source {s}")
        print(f"{s}: {len(out[s])} new leads in {time.time() - t0:.0f}s", file=sys.stderr)
    return out


def backtest(sources, since):
    cat = [r for r in json.loads((ROOT / "data/vulnerabilities.json").read_text()) if r["disclosure_date"] >= since]
    want = {c.upper() for r in cat for c in r.get("cves", [])} | {r["id"].upper() for r in cat if not r.get("cves")}
    found = {}
    for s in sources:
        if s == "cvelist":
            leads = vuln.cvelist_ids(sorted(c for c in want if c.startswith("CVE-")))
        elif s == "osv":
            leads = vuln.osv()
        elif s == "mozilla":
            leads = vuln.mozilla()
        elif s == "labs":
            leads = [x for n in vuln.LAB_INDEXES for x in vuln.lab_index(n)]
        found[s] = {i for ld in leads for i in ld["ids"]} & want
    union = set().union(*found.values()) if found else set()
    print(f"catalog records since {since}: {len(cat)}; ids to find: {len(want)}")
    for s, f in found.items():
        print(f"  {s}: {len(f)} ({100 * len(f) // max(1, len(want))}%)")
    print(f"  union: {len(union)} ({100 * len(union) // max(1, len(want))}%)")
    missed = sorted(want - union)
    print("  missed sample:", missed[:10])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sources", default="cvelist_delta,mozilla,labs")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--backtest", action="store_true")
    p.add_argument("--since", default="2026-09-01")
    p.add_argument("--cleanup", action="store_true", help="delete raw downloads afterwards")
    p.add_argument("--out", type=Path)
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--job-id", help="stable checkpoint job identity across restored directories")
    p.add_argument("--page-budget", type=int, help="delta records / OSV ecosystems per invocation")
    a = p.parse_args(argv)
    sources = a.sources.split(",")
    try:
        if a.backtest:
            backtest(sources, a.since)
        else:
            if a.days < 1 or (a.page_budget is not None and a.page_budget < 1):
                p.error("--days and --page-budget must be positive")
            path = a.out or ROOT / "work/harvest/leads" / time.strftime("%Y-%m-%d") / "vuln.jsonl"
            checkpoint = a.checkpoint or Path(str(path) + '.state.json')
            source_keys = [key for name in sources for key in (['lab:' + lab for lab in vuln.LAB_INDEXES] if name == 'labs' else [name])]
            previous = state.get_job(state.load(checkpoint), path, source_keys, a.job_id)
            until = previous.get('window', {}).get('to') or dt.datetime.now(dt.timezone.utc).isoformat()[:19]
            since = previous.get('window', {}).get('from') or (dt.datetime.fromisoformat(until) - dt.timedelta(days=a.days)).isoformat()[:19]
            known = kn.Known()
            adapters = {}
            for name in sources:
                if name == 'cvelist_delta':
                    adapters[name] = functools.partial(incremental_delta, since, until, known)
                elif name == 'osv':
                    adapters[name] = functools.partial(incremental_osv, known)
                elif name == 'mozilla':
                    adapters[name] = functools.partial(complete_mozilla, known)
                elif name == 'labs':
                    for lab in vuln.LAB_INDEXES:
                        adapters['lab:' + lab] = functools.partial(index_adapter, lab, known)
                else:
                    p.error(f"unknown source {name}")
            leads, report = state.collect_sources(adapters, {'from': since, 'to': until}, path, checkpoint, a.page_budget, a.job_id)
            print(f"{len(leads)} persisted leads -> {path}; coverage: {report['status']}")
            return 0 if report['status'] == 'complete' else 1
    finally:
        if a.cleanup:
            fetch.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
