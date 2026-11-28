"""Collect one weekly row of adoption and catalog metrics as CSV.

python3 scripts/collect_metrics.py --output metrics.csv
Each external source is optional: a failure leaves its columns empty and is reported on stderr.
GitHub traffic needs a token with repository administration read access (METRICS_TOKEN);
without it those columns stay empty.
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = 'marcello-pichini/ai-science-tracker'
HF_URL = ('https://huggingface.co/api/datasets/' + REPO
          + '?expand%5B%5D=downloads&expand%5B%5D=downloadsAllTime&expand%5B%5D=likes')
ZENODO_URL = 'https://zenodo.org/api/records/24217686'  # concept record; resolves to the latest version
GITHUB_API = 'https://api.github.com/repos/' + REPO
USER_AGENT = 'ai-science-tracker-metrics/1.0'
COLUMNS = ['date', 'hf_downloads_30d', 'hf_downloads_all_time', 'hf_likes',
           'zenodo_downloads', 'zenodo_unique_downloads', 'zenodo_views', 'zenodo_unique_views',
           'github_stars', 'github_open_issues', 'github_views_14d', 'github_uniques_14d',
           'discoveries', 'discoveries_verified', 'discoveries_needs_verification',
           'verified_abstract_only', 'vulnerabilities']

# shortcut: wording heuristic over free-text scopes; replace with a structured review_depth field once the data has one.
ABSTRACT = re.compile(r'abstract', re.I)
NOT_READ = re.compile(r'full[- ]?text (was |were )?not|not (otherwise )?(read|accessed|assessed)|abstract[^.;]*\bonly\b', re.I)
FULL_TEXT = re.compile(r'full[- ]text (Methods|excerpt)|Methods/Results excerpts', re.I)


def fetch_json(url, token=None):
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def abstract_only(record):
    scope = (record.get('source_review') or {}).get('scope') or ''
    return bool(ABSTRACT.search(scope) and NOT_READ.search(scope) and not FULL_TEXT.search(scope))


def catalog_metrics(root):
    discoveries = json.loads((root / 'data/discoveries.json').read_text())
    overview = json.loads((root / 'data/vulnerabilities-overview.json').read_text())
    verified = [r for r in discoveries if r.get('verification_status') == 'verified']
    return {'discoveries': len(discoveries), 'discoveries_verified': len(verified),
            'discoveries_needs_verification': sum(r.get('verification_status') == 'needs verification' for r in discoveries),
            'verified_abstract_only': sum(map(abstract_only, verified)),
            'vulnerabilities': overview['totals']['rows']}


def huggingface(fetch):
    data = fetch(HF_URL)
    return {'hf_downloads_30d': data.get('downloads'), 'hf_downloads_all_time': data.get('downloadsAllTime'),
            'hf_likes': data.get('likes')}


def zenodo(fetch):
    stats = fetch(ZENODO_URL)['stats']  # unprefixed stats cover all versions; version_* only the latest
    return {'zenodo_' + key: stats.get(key) for key in ('downloads', 'unique_downloads', 'views', 'unique_views')}


def github(fetch):
    data = fetch(GITHUB_API)
    return {'github_stars': data.get('stargazers_count'), 'github_open_issues': data.get('open_issues_count')}


def github_traffic(fetch, token):
    if not token:
        raise RuntimeError('no METRICS_TOKEN; traffic skipped')
    data = fetch(GITHUB_API + '/traffic/views', token)
    return {'github_views_14d': data.get('count'), 'github_uniques_14d': data.get('uniques')}


def build_row(root=ROOT, fetch=fetch_json, token=None, today=None, log=sys.stderr):
    row = dict.fromkeys(COLUMNS, '')
    row['date'] = (today or datetime.datetime.now(datetime.timezone.utc).date()).isoformat()
    sources = [('catalog', lambda: catalog_metrics(root)), ('huggingface', lambda: huggingface(fetch)),
               ('zenodo', lambda: zenodo(fetch)), ('github', lambda: github(fetch)),
               ('github-traffic', lambda: github_traffic(fetch, token))]
    for name, collect in sources:
        try:
            row.update({k: '' if v is None else v for k, v in collect().items()})
        except Exception as error:  # one failing source must not drop the others
            print(f'::warning::metrics source {name} skipped: {error}', file=log)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='CSV file to append to (header written when new)')
    args = parser.parse_args()
    row = build_row(token=os.environ.get('METRICS_TOKEN'))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        new = not args.output.exists()
        with args.output.open('a', newline='') as handle:
            writer = csv.DictWriter(handle, COLUMNS)
            if new:
                writer.writeheader()
            writer.writerow(row)
    writer = csv.DictWriter(sys.stdout, COLUMNS)
    writer.writeheader()
    writer.writerow(row)


if __name__ == '__main__':
    main()
