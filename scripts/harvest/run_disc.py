#!/usr/bin/env python3
"""Discovery harvest by month windows: adapters -> dedupe -> leads jsonl, plus a recall backtest.

  python3 scripts/harvest/run_disc.py --from 2024-03-01 --to 2024-03-31 --sources openalex,arxiv,biorxiv,europepmc
  python3 scripts/harvest/run_disc.py --backtest --months 2022-06,2024-03,2025-09
Leads go to work/harvest/leads/<date>/disc-<from>.jsonl (not committed).
"""
import argparse
import calendar
import json
import re
import sys
import time
import functools
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harvest import disc, known as kn, state  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def month_bounds(m):
    y, mo = map(int, m.split("-"))
    return f"{m}-01", f"{m}-{calendar.monthrange(y, mo)[1]:02d}"


def collect(sources, start, end, min_score):
    out = []
    for s in sources:
        t0 = time.time()
        try:
            rows = []
            for row in disc.ADAPTERS[s](start, end, min_score):
                rows.append(row)
        except Exception as e:  # one source failing must not hide the others
            print(f"  {s}: ERROR {str(e)[:80]}", file=sys.stderr)
            out += rows
            continue
        print(f"  {s}: {len(rows)} leads {start}..{end} in {time.time() - t0:.0f}s", file=sys.stderr)
        out += rows
    return out


def is_known(k, ld):
    ax = next((i[6:] for i in ld["ids"] if i.startswith("arXiv:")), None)
    return (k.paper(arxiv=ax, title=ld["title"], key=ld["key"], url=ld["key"] if ld["key"].startswith('https://') else None)
            or any(k.paper(url=i) for i in ld['ids'] if i.startswith('https://'))
            or any(k.paper(doi=i) for i in ld["ids"] if i.startswith("10.")))


def backtest(sources, months, min_score):
    cat = json.loads((ROOT / "data/discoveries.json").read_text())
    for m in months:
        start, end = month_bounds(m)
        want = {}
        for r in cat:
            if r["publication_date"][:7] != m:
                continue
            blob = f"{r.get('paper_url', '')} {r['source_url']}"
            d = kn.DOI_RE.search(blob)
            a = kn.ARXIV_RE.search(blob)
            key = kn.norm_doi(d.group(0)) if d else (f"arXiv:{a.group(1) or a.group(2)}" if a else None)
            if key:
                want[key] = r["id"]
        leads = collect(sources, start, end, 1)
        print(f"{m}: catalog records with DOI/arXiv: {len(want)}; sources {sources}")
        for t in (1, 2, 3, 4, 5):
            sel = [ld for ld in leads if ld["signal"] >= t]
            f = {i for ld in sel for i in ld["ids"]} & set(want)
            print(f"   score>={t}: {len(sel)} leads, finds {len(f)} of {len(want)} ({100 * len(f) // max(1, len(want))}%)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="start")
    p.add_argument("--to", dest="end")
    p.add_argument("--sources", default="openalex,arxiv,biorxiv,europepmc,labs")
    p.add_argument("--min-score", type=int, default=0)
    p.add_argument("--backtest", action="store_true")
    p.add_argument("--months", default="2022-06,2024-03,2025-09")
    p.add_argument("--out", type=Path)
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--job-id", help="stable checkpoint job identity across restored directories")
    p.add_argument("--page-budget", type=int, help="maximum pages per source per invocation; incomplete exits nonzero")
    a = p.parse_args(argv)
    sources = a.sources.split(",")
    if a.backtest:
        backtest(sources, a.months.split(","), a.min_score)
        return 0
    if not (a.start and a.end):
        p.error("--from and --to are required")
    if any(name not in disc.ADAPTERS for name in sources):
        p.error("unknown source")
    if a.page_budget is not None and a.page_budget < 1:
        p.error("--page-budget must be positive")
    d = ROOT / "work/harvest/leads" / time.strftime("%Y-%m-%d")
    path = a.out or d / f"disc-{a.start}.jsonl"
    checkpoint = a.checkpoint or Path(str(path) + ".state.json")
    adapters = {name: functools.partial(disc.ADAPTERS[name], a.start, a.end, a.min_score) for name in sources}
    leads, report = state.collect_sources(adapters, {"from": a.start, "to": a.end, "min_score": a.min_score}, path, checkpoint, a.page_budget, a.job_id)
    print(f"{len(leads)} persisted leads -> {path}; coverage: {report['status']}")
    return 0 if report['status'] == 'complete' else 1


if __name__ == "__main__":
    sys.exit(main())
