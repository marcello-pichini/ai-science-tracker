"""Fetch field- and year-normalized citation percentiles from OpenAlex into data/citations.json.

Run by hand now and then (needs network): python3 scripts/fetch_citations.py
OpenAlex data is CC0. Citations show attention, not correctness; they never feed the relevance score.
Works younger than one year are skipped because their percentile is not yet meaningful.
"""
import datetime, json, math, os, re, tempfile, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_AGE_DAYS = 365


def normalized_doi(value):
    if not isinstance(value, str):
        raise ValueError('DOI must be a string')
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value, flags=re.I).lower()
    if not re.fullmatch(r'''10\.\d{4,9}/[^\s?#<>"'`\\]+''', doi):
        raise ValueError(f'Invalid DOI: {value!r}')
    return doi


def doi_of(record):
    for url in (record['paper_url'], record['source_url']):
        m = re.search(r'10\.\d{4,9}/[^\s?#]+', url or '')
        if m:
            return normalized_doi(m.group(0).rstrip('/.'))
        m = re.search(r'nature\.com/articles/([\w.-]+)', url or '')
        if m:
            return normalized_doi('10.1038/' + m.group(1))
    return None


def fetch(dois):
    query = urllib.parse.urlencode({'filter': 'doi:' + '|'.join(dois), 'per-page': 100,
                                    'select': 'doi,locations,publication_date,cited_by_count,citation_normalized_percentile'})
    req = urllib.request.Request('https://api.openalex.org/works?' + query, headers={'User-Agent': 'ai-science-tracker'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['results']


def citation_of(work, today):
    doi = normalized_doi(work['doi'])
    count = work['cited_by_count']
    if type(count) is not int or count < 0:
        raise ValueError('Citation count must be a nonnegative integer')
    pub = work.get('publication_date')
    if pub is not None:
        if not isinstance(pub, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', pub):
            raise ValueError('Invalid citation publication date')
        pub = datetime.date.fromisoformat(pub)
    pct = work.get('citation_normalized_percentile')
    if pct is None:
        return None
    value = pct['value']
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Citation percentile must be between zero and one')
    for key in ('is_in_top_1_percent', 'is_in_top_10_percent'):
        if type(pct[key]) is not bool:
            raise ValueError('Citation percentile flags must be booleans')
    if pub is None or (today - pub).days < MIN_AGE_DAYS:
        return None
    return {'doi': doi, 'percentile': round(value * 100, 1),
            'top_1': pct['is_in_top_1_percent'], 'top_10': pct['is_in_top_10_percent'],
            'cited_by': count}


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
        requested = set(dois[i:i + 50])
        matched = set()
        for work in fetch(sorted(requested)):
            citation = citation_of(work, today)
            aliases = {normalized_doi(work['doi'])}
            aliases.update(normalized_doi(location['doi']) for location in work.get('locations', []) if location.get('doi'))
            matches = requested & aliases
            matched.update(matches)
            if citation is not None:
                for doi in matches:
                    for rid in by_doi[doi]:
                        out[rid] = citation
        # List responses can truncate locations; a singleton DOI filter retains request identity.
        for doi in sorted(requested - matched):
            works = fetch([doi])
            if len(works) > 1:
                raise ValueError(f'Ambiguous OpenAlex DOI match: {doi}')
            if works:
                citation = citation_of(works[0], today)
                if citation is not None:
                    for rid in by_doi[doi]:
                        out[rid] = citation
    data = {'checked': today.isoformat(), 'source': 'OpenAlex (CC0), citation_normalized_percentile',
            'source_url': 'https://openalex.org', 'records': dict(sorted(out.items()))}
    serialized = json.dumps(data, indent=1, allow_nan=False) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=ROOT / 'data', delete=False) as target:
            temporary = Path(target.name)
            target.write(serialized)
        os.replace(temporary, ROOT / 'data/citations.json')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f'{len(out)} records with a percentile, of {len(records)} ({len(dois)} DOIs looked up)')


if __name__ == '__main__':
    main()
