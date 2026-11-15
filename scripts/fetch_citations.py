"""Fetch field- and year-normalized citation percentiles from OpenAlex into data/citations.json.

Run by hand now and then (needs network): python3 scripts/fetch_citations.py
OpenAlex data is CC0. Citations show attention, not correctness; they never feed the relevance score.
Works younger than one year are skipped because their percentile is not yet meaningful.
"""
import datetime, json, re, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_AGE_DAYS = 365


def doi_of(record):
    for url in (record['paper_url'], record['source_url']):
        m = re.search(r'10\.\d{4,9}/[^\s?#]+', url or '')
        if m:
            return m.group(0).rstrip('/.').lower()
        m = re.search(r'nature\.com/articles/([\w.-]+)', url or '')
        if m:
            return '10.1038/' + m.group(1).lower()
    return None


def fetch(dois):
    query = urllib.parse.urlencode({'filter': 'doi:' + '|'.join(dois), 'per-page': 100,
                                    'select': 'doi,publication_date,cited_by_count,citation_normalized_percentile'})
    req = urllib.request.Request('https://api.openalex.org/works?' + query, headers={'User-Agent': 'ai-science-tracker'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['results']


def main():
    today = datetime.date.today()
    records = json.loads((ROOT / 'data/discoveries.json').read_text())
    by_doi = {}
    for rec in records:
        doi = doi_of(rec)
        if doi:
            by_doi.setdefault(doi, []).append(rec['id'])
    dois, out = sorted(by_doi), {}
    for i in range(0, len(dois), 50):
        for w in fetch(dois[i:i + 50]):
            pct, pub = w.get('citation_normalized_percentile'), w.get('publication_date')
            if not pct or not pub or (today - datetime.date.fromisoformat(pub)).days < MIN_AGE_DAYS:
                continue
            doi = w['doi'].removeprefix('https://doi.org/').lower()
            for rid in by_doi.get(doi, []):
                out[rid] = {'doi': doi, 'percentile': round(pct['value'] * 100, 1),
                            'top_1': pct['is_in_top_1_percent'], 'top_10': pct['is_in_top_10_percent'],
                            'cited_by': w['cited_by_count']}
    data = {'checked': today.isoformat(), 'source': 'OpenAlex (CC0), citation_normalized_percentile',
            'source_url': 'https://openalex.org', 'records': dict(sorted(out.items()))}
    (ROOT / 'data/citations.json').write_text(json.dumps(data, indent=1) + '\n')
    print(f'{len(out)} records with a percentile, of {len(records)} ({len(dois)} DOIs looked up)')


if __name__ == '__main__':
    main()
