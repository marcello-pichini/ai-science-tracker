"""Collect first-party blog candidates with a machine-readable source coverage report."""
import argparse
from datetime import date
import json
from pathlib import Path

from . import blog_sources, disc
from .known import Known
from .run_disc import is_known


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='start', required=True)
    parser.add_argument('--to', dest='end', required=True)
    parser.add_argument('--sources', default=','.join(blog_sources.SOURCES))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if date.fromisoformat(args.start) > date.fromisoformat(args.end):
        parser.error('The start date must not follow the end date')
    names = list(dict.fromkeys(args.sources.split(',')))
    if not set(names) <= blog_sources.SOURCES.keys():
        parser.error('Unknown blog source')
    index, cases, reports = Known(), {}, []
    for name in names:
        report = {}
        matched, prior = 0, 0
        for row in disc.research_blog(name, args.start, args.end, report):
            matched += 1
            if is_known(index, row):
                prior += 1
            else:
                cases.setdefault(row['key'], row)
        report.update(window_start=args.start, window_end=args.end, in_window_or_undated=matched, known=prior)
        reports.append(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'blog-leads.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in cases.values()))
    (args.out / 'blog-coverage.json').write_text(json.dumps({'sources': reports, 'unique_candidates': len(cases)}, indent=2) + '\n')
    print(f'{len(cases)} unique candidates from {len(reports)} sources; coverage saved in {args.out}')
    return int(any(r.get('status') != 'ok' for r in reports))


if __name__ == '__main__':
    raise SystemExit(main())
