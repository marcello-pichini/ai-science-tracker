"""Exact-byte component metadata; deterministic identity is separate from source dates."""
import csv
import hashlib
import json
import re
from pathlib import Path

CATALOG_DOI = 'https://doi.org/10.5281/zenodo.24217686'
RELEASES = 'https://github.com/marcello-pichini/ai-science-tracker/releases'
COMPONENTS = {
    'discoveries': ('Scientific discoveries', 'active scientific catalog entries', 'CC BY 4.0', 'Manual and incomplete; entries can overlap or bundle findings.'),
    'archived-discoveries': ('Archived discoveries', 'historical catalog entries', 'CC BY 4.0', 'Retained historical records; excluded from active science totals.'),
    'vulnerabilities': ('AI-found vulnerabilities', 'source-attributed cases', 'CC BY 4.0', 'Manual and incomplete; cases and distinct CVEs are different units.'),
    'models': ('Notable model releases', 'selected Epoch model releases', 'CC BY 4.0; attribute Epoch AI', 'Selected notable releases; overlaps model-progress inventory.'),
    'model-progress': ('Model progress', 'Epoch source entries', 'CC BY 4.0; attribute Epoch AI', 'Selected source entries; missing ECI and benchmark values are not zero.'),
    'swe-bench': ('SWE-bench Verified', 'mini-SWE-agent evaluation runs', 'CC BY-NC 4.0', 'Separate configurations, not unique models; excluded from current Hugging Face catalog export. Noncommercial reuse only.'),
    'citations': ('Citation metadata', 'OpenAlex records matched to catalog IDs', 'CC0; OpenAlex metadata', 'Selective matching; citation counts do not measure scientific evidence strength.'),
    'entity-aliases': ('Reviewed entity aliases', 'reviewed entity groups', 'CC BY 4.0', 'Exact aliases only; original labels and model-version uncertainty remain in records.'),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def span(rows, key):
    values = sorted(r[key] for r in rows if r.get(key))
    return {'first': values[0], 'last': values[-1]} if values else None


def benchmark_descriptors(root):
    registry_path = 'data/benchmarks/index.json'
    raw = (root / registry_path).read_bytes()
    registry = json.loads(raw)
    sources = registry['sources']
    if len({source['id'] for source in sources}) != len(sources):
        raise ValueError('Duplicate benchmark source identity')
    descriptors = {'benchmark-registry': {'path': registry_path, 'label': 'Independent benchmark directory',
        'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'count': len(sources),
        'unit': 'separately licensed source components', 'dates': {'directory_retrieved_on': registry.get('retrieved_on')},
        'source_urls': ['https://aisciencetracker.org/docs/public-benchmarks.md'],
        'license': 'Per-component terms; no blanket catalog license', 'coverage': registry['scope'],
        'group': 'public-benchmarks', 'catalog_doi': None, 'doi_note': 'Source components retain their own identity and license.', 'release_url': RELEASES}}
    for source in sources:
        sid = source['id']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', sid) or source['path'] != f'data/benchmarks/{sid}.json':
            raise ValueError('Unsafe benchmark component identity/path')
        content = (root / source['path']).read_bytes()
        data = json.loads(content)
        rows = data['records']
        digest = hashlib.sha256(content).hexdigest()
        if digest != source['sha256'] or len(rows) != source['record_count']:
            raise ValueError('Benchmark registry and component bytes differ')
        for key in ('id', 'name', 'license', 'license_url', 'license_notice', 'attribution', 'selection', 'scope', 'retrieved_on', 'maintenance', 'source_url'):
            if source[key] != data[key]:
                raise ValueError('Benchmark registry metadata differs: ' + key)
        descriptors['benchmark-' + sid] = {'path': source['path'], 'label': data['name'], 'sha256': digest,
            'bytes': len(content), 'count': len(rows), 'unit': 'source numerical observations',
            'record_units': sorted({row['unit'] for row in rows}),
            'dates': {'snapshot_retrieved_on': data['retrieved_on'], 'source_observation_dates': span(rows, 'date')},
            'source_date_basis': sorted({row['date_basis'] for row in rows}),
            'source_urls': [data['source_url']], 'license': data['license'], 'license_url': data['license_url'],
            'license_notice': data['license_notice'], 'attribution': data['attribution'], 'changes': data['changes'],
            'coverage': data['scope'], 'selection': data['selection'], 'maintenance': data['maintenance'],
            'group': 'public-benchmarks', 'hugging_face_export': False, 'catalog_doi': None,
            'doi_note': 'No component DOI assigned here; the catalog archive does not replace source citation.', 'release_url': RELEASES}
    return descriptors


def build_manifest(root):
    root = Path(root)
    components = {}
    for key, (label, unit, license_name, coverage) in COMPONENTS.items():
        path = f'data/{key}.json'
        raw = (root / path).read_bytes()
        data = json.loads(raw)
        rows = data if isinstance(data, list) else data.get('models', data.get('records', []))
        count = len(data['organizations']) + len(data['systems']) if key == 'entity-aliases' else len(rows)
        dates, sources = {}, []
        if key in ('discoveries', 'archived-discoveries'):
            dates = {'publication_dates': span(rows, 'publication_date'), 'addition_dates': span(rows, 'added_date')}
            sources = ['https://aisciencetracker.org/methodology.html']
        elif key == 'vulnerabilities':
            dates = {k: span(rows, k) for k in ('disclosure_date', 'ai_attribution_date', 'checked_date')}
            sources = ['https://aisciencetracker.org/security.html#t-context']
        elif key == 'models':
            dates = {'generated_on': data.get('generated'), 'source_downloaded_on': data.get('source', {}).get('downloaded'), 'release_dates': span(rows, 'date')}
            sources = [data.get('source', {}).get('url') or 'https://epoch.ai/data/notable-ai-models']
        elif key == 'model-progress':
            dates = {'snapshot_retrieved_on': data.get('fetched_on'), 'recorded_dates': span(rows, 'date')}
            sources = [data['source_url']]
        elif key == 'swe-bench':
            dates = {'snapshot_retrieved_on': data.get('fetched_on'), 'evaluation_dates': span(rows, 'evaluation_date')}
            sources = [data['source_url']]
        elif key == 'citations':
            dates = {'metadata_checked_on': data.get('checked')}
            sources = [data['source_url']]
        elif key == 'entity-aliases':
            dates = {'alias_review_dates': span(data['organizations'] + data['systems'], 'reviewed_on')}
            sources = sorted({u for row in data['organizations'] + data['systems'] for u in row.get('source_urls', [])})
        components[key] = {'path': path, 'label': label, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                           'count': count, 'unit': unit, 'dates': dates, 'source_urls': sources, 'license': license_name,
                           'coverage': coverage, 'release_url': RELEASES,
                           'catalog_doi': CATALOG_DOI if key in ('discoveries','archived-discoveries','vulnerabilities') else None,
                           'doi_note': 'Catalog archive DOI; upstream sources retain their own identity and license.'}
        if key == 'swe-bench':
            components[key].update(license_url=data['license_url'], license_notice=data['license_notice'],
                                   attribution=data['attribution'], changes=data['changes'], hugging_face_export=False)
        if key == 'model-progress':
            components[key]['coverage_counts'] = {'eci': sum(m.get('eci') is not None for m in rows),
                'any_displayed_benchmark': sum(any(m.get('benchmarks', {}).get(b['id'], {}).get('score') is not None for b in data['benchmarks']) for m in rows), 'total': len(rows)}
        if key == 'vulnerabilities':
            components[key]['distinct_cves'] = len({cve for r in rows for cve in r['cves']})
    for key in ('discoveries', 'vulnerabilities'):
        path = f'data/{key}.csv'
        raw = (root / path).read_bytes()
        components[key + '-csv'] = dict(components[key], path=path, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    path = 'data/catalog-summary.csv'
    raw = (root / path).read_bytes()
    summary_rows = list(csv.DictReader(raw.decode('utf-8').splitlines()))
    components['catalog-summary'] = {'path': path, 'label': 'Catalog coverage summary', 'sha256': hashlib.sha256(raw).hexdigest(),
        'bytes': len(raw), 'count': len(summary_rows), 'unit': 'overlapping year/field aggregate rows',
        'dates': components['discoveries']['dates'], 'source_urls': ['https://aisciencetracker.org/profiles/catalog-evidence.html'],
        'license': 'CC BY 4.0', 'coverage': 'Each grouping separately sums to active catalog entries; never add the year and field groupings together. Counts describe collection coverage, not independent findings.',
        'catalog_doi': CATALOG_DOI, 'doi_note': 'Catalog archive DOI; choose a matching release for stable citation.', 'release_url': RELEASES}
    components.update(benchmark_descriptors(root))
    return {'schema_version': 1, 'scope': 'Current public collection files; snapshot identity is not a review or publication timestamp.',
            'snapshot_sha256': hashlib.sha256(canonical(components)).hexdigest(), 'components': components}


def write_manifest(root):
    value = build_manifest(root)
    out = Path(root) / 'api/v1/manifest.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return value


def stamp_pages(root, snapshot):
    for name in ('index','profile','models','search','security','model-progress','methodology','dataset'):
        path = Path(root) / (name + '.html')
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8')
        text = re.sub(r'(<html\b[^>]*?) data-page-snapshot="[^"]*"', r'\1', text, count=1)
        text = text.replace('<html lang="en"', f'<html lang="en" data-page-snapshot="{snapshot}"', 1)
        path.write_text(text, encoding='utf-8')


def write_component_jsonld(root, manifest):
    path = Path(root) / 'dataset.html'
    if not path.exists():
        return
    datasets = []
    for key, component in manifest['components'].items():
        if component.get('group') != 'public-benchmarks' or key == 'benchmark-registry':
            continue
        datasets.append({'@type': 'Dataset', '@id': 'https://aisciencetracker.org/' + component['path'],
            'name': component['label'], 'description': component['coverage'], 'license': component['license_url'],
            'creditText': component['attribution'], 'url': 'https://aisciencetracker.org/' + component['path'],
            # The upstream benchmark authors created the data; this site only selects and republishes it.
            'creator': {'@type': 'Organization', 'name': component['attribution'],
                        **({'url': component['source_urls'][0]} if component.get('source_urls') else {})},
            'distribution': {'@type': 'DataDownload', 'encodingFormat': 'application/json', 'contentUrl': 'https://aisciencetracker.org/' + component['path']}})
    block = '<script id="component-datasets" type="application/ld+json">\n' + json.dumps({'@context': 'https://schema.org/', '@graph': datasets}, ensure_ascii=False).replace('<', '\\u003c') + '\n</script>'
    page = path.read_text(encoding='utf-8')
    pattern = r'<script id="component-datasets" type="application/ld\+json">.*?</script>'
    page = re.sub(pattern, lambda _: block, page, flags=re.S) if re.search(pattern, page, re.S) else page.replace('</head>', block + '\n</head>', 1)
    path.write_text(page, encoding='utf-8')
