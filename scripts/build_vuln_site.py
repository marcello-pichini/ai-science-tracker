"""Small site files from the global vulnerability build (scripts/build_vuln_global.py).

    python3 scripts/build_vuln_site.py [--build work/vuln-global/build] [--out data] [--today YYYY-MM-DD]

Writes data/vulnerabilities-preview.json (the vulnerabilities the site lists: every one marked "act now", plus every
critical one published in the last 365 days) and data/vulnerabilities-overview.json (totals, charts, categories,
sources and notices). The full dataset is published elsewhere (Hugging Face, Kaggle, Zenodo), never on the site.
"""
import argparse
import collections
import datetime
import gzip
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW_DAYS = 365
CRITICAL = 9.0
TOP = 15
LEAD_MAX = 80  # characters of description kept for untitled rows; keeps the preview well under 5 MB
CATEGORY_MIN = 20  # categories below this get no page of their own (no thin pages)

# One line per source: name, licence or terms, the notice shown wherever the data is published.
# Mirrors docs/vulnerability-sources.md; reference-only sources contribute IDs and links, never text.
SOURCES = [
    ('CVE List (MITRE, CVE Program)', 'CVE Terms of Use', 'CVE® records © The MITRE Corporation, reproduced under the CVE Terms of Use.', 'https://www.cve.org/Legal/TermsOfUse'),
    ('CISA ADP (in CVE records)', 'CVE Terms of Use', 'SSVC decision points, CWE and affected products added to CVE records by CISA.', 'https://www.cve.org/Legal/TermsOfUse'),
    ('NVD (NIST)', 'NVD terms of use', 'This product uses the NVD API but is not endorsed or certified by the NVD.', 'https://nvd.nist.gov/developers/terms-of-use'),
    ('CISA Known Exploited Vulnerabilities', 'CC0 1.0', 'CISA KEV catalog, public domain dedication.', 'https://www.cisa.gov/known-exploited-vulnerabilities-catalog'),
    ('FIRST EPSS', 'Attribution requested', 'EPSS scores by FIRST (first.org/epss), with the score date.', 'https://www.first.org/epss/'),
    ('ENISA EU Vulnerability Database', 'ENISA legal notice', 'Source: ENISA, EU Vulnerability Database (euvd.enisa.europa.eu).', 'https://euvd.enisa.europa.eu/'),
    ('GitHub Advisory Database (via OSV)', 'CC BY 4.0', 'GitHub Advisory Database, CC BY 4.0; advisory link kept on every row.', 'https://github.com/github/advisory-database'),
    ('PyPI, PSF, Go, RustSec, OSS-Fuzz, Haskell, Julia, opam, Drupal advisories (via OSV)', 'CC BY 4.0 or CC0, per source', 'Each row keeps its original source name, licence and advisory link.', 'https://osv.dev/'),
    ('MITRE CWE', 'CWE Terms of Use', 'CWE™ © The MITRE Corporation, reproduced under the CWE Terms of Use.', 'https://cwe.mitre.org/about/termsofuse.html'),
    ('MITRE CAPEC (with its ATT&CK mappings)', 'CAPEC Terms of Use', 'CAPEC™ © The MITRE Corporation, reproduced under the CAPEC Terms of Use.', 'https://capec.mitre.org/about/termsofuse.html'),
    ('Metasploit module metadata', 'BSD-3-Clause', 'Module names and links from the Metasploit Framework, BSD-3-Clause.', 'https://github.com/rapid7/metasploit-framework'),
    ('Nuclei templates', 'MIT', 'Template paths and links from projectdiscovery/nuclei-templates, MIT.', 'https://github.com/projectdiscovery/nuclei-templates'),
    ('PoC-in-GitHub (nomi-sec)', 'CC0 1.0', 'Repository links, unverified: they may be fake or malicious.', 'https://github.com/nomi-sec/PoC-in-GitHub'),
    ('Exploit-DB', 'Reference only', 'Exploit IDs and links only; no titles or code.', 'https://www.exploit-db.com/'),
    ('CERT-FR', 'Licence Ouverte 2.0', 'Source: CERT-FR (ANSSI), Licence Ouverte 2.0.', 'https://cert.cyber.gouv.fr/'),
    ('CIRCL GCVE (GNA-1) and sightings', 'CC BY 4.0', 'Source: CIRCL Vulnerability-Lookup, CC BY 4.0; sightings as counts only.', 'https://vulnerability.circl.lu/'),
    ('Vendor and CERT CSAF feeds (via CIRCL)', 'Reference only', 'Advisory IDs and links only.', 'https://vulnerability.circl.lu/'),
    ('JVN iPedia, CNVD, FSTEC BDU, VARIoT', 'Reference only', 'IDs and links only.', 'https://vulnerability.circl.lu/'),
    ('endoflife.date', 'MIT', 'Product lifecycle dates from endoflife.date, MIT.', 'https://endoflife.date/'),
    ('FIRST CVSS v4.0 calculator tables', 'BSD-2-Clause', 'CVSS v4.0 scoring tables © FIRST, Red Hat and contributors, BSD-2-Clause.', 'https://github.com/FIRSTdotorg/cvss-v4-calculator'),
    ('AI Science Tracker derived fields', 'CC BY 4.0', 'Product families, categories, primary severity, priority, summary and counts are ours, CC BY 4.0.', 'https://aisciencetracker.org/'),
]


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def links(row_id):
    """Record links built from the ID; the page builds the same ones, so the preview file does not carry them."""
    if row_id.startswith('CVE-'):
        return {'cve': f'https://www.cve.org/CVERecord?id={row_id}', 'nvd': f'https://nvd.nist.gov/vuln/detail/{row_id}'}
    if row_id.startswith(('CNVD', 'VAR', 'BDU', 'JVNDB')):
        return {}
    return {'osv': f'https://osv.dev/vulnerability/{row_id}'}


def in_preview(row, since):
    if row['state'] != 'PUBLISHED':
        return False
    if (row['priority'] or {}).get('level') == 'act now':
        return True
    score = (row['severity'] or {}).get('score')
    return score is not None and score >= CRITICAL and (row['published'] or '')[:10] >= since


def slim(row):
    sev = row['severity'] or {}
    # The products most sources name first (log4j before an app that bundles it), as the row summary does.
    ranked = sorted(row['products'], key=lambda p: (-len(p.get('sources') or []), p['product_key']))
    products = ranked[:3]
    # No summary or ID-derived links: they would double the file (under 5 MB keeps the page light).
    # No title: the description's first sentence, short, so the entry still says what it is.
    lead = None if row['title'] else re.split(r'(?<=[.;])\s', (row['description'] or '').strip(), 1)[0][:LEAD_MAX] or None
    out = {'id': row['id'], 'title': row['title'] or None, 'description': lead, 'published': (row['published'] or '')[:10] or None,
            'score': sev.get('score'), 'band': sev.get('band') or 'unscored', 'score_source': sev.get('source'),
            'priority': (row['priority'] or {}).get('level'), 'kev_added': (row['kev'] or {}).get('date_added'),
            'epss': (row['epss'] or {}).get('score'), 'products': [p['product_key'] for p in products],
            'category': next((p['category'] for p in ranked if p.get('category')), None),
            'classes': row['vuln_class'][:3],
            'advisory': next((u for u in sorted((row.get('remediation') or {}).get('vendor_advisory_urls') or [],
                                                key=lambda u: not u.startswith('https://')) if u.startswith(('https://', 'http://'))), None)}
    return {k: v for k, v in out.items() if v not in (None, [])}  # absent key = not stated by the sources


def export(build, out, today):
    since = (datetime.date.fromisoformat(today) - datetime.timedelta(days=PREVIEW_DAYS)).isoformat()
    report = json.loads((build / 'build_report.json').read_text())
    preview = []
    c = {k: collections.Counter() for k in ('by_year', 'by_band', 'by_priority', 'by_maturity', 'classes')}
    cats = collections.defaultdict(lambda: {'total': 0, 'kev': 0, 'public_exploit': 0, 'by_year': collections.Counter(),
                                            'classes': collections.Counter()})
    with gzip.open(build / 'vulnerabilities_global.jsonl.gz', 'rt') as f:
        for line in f:
            row = json.loads(line)
            if row['state'] != 'PUBLISHED':
                continue
            year = (row['published'] or '')[:4] or 'unknown'
            c['by_year'][year] += 1
            c['by_band'][(row['severity'] or {}).get('band') or 'unscored'] += 1
            c['by_priority'][(row['priority'] or {}).get('level') or 'unknown'] += 1
            c['by_maturity'][row['exploit_summary'].get('maturity') or 'none known'] += 1
            c['classes'].update(row['vuln_class'])
            for name in sorted({p['category'] for p in row['products'] if p.get('category')}):
                k = cats[name]
                k['total'] += 1
                k['kev'] += row['kev'] is not None
                k['public_exploit'] += bool(row['exploit_summary'].get('public_exploit'))
                k['by_year'][year] += 1
                k['classes'].update(row['vuln_class'])
            if in_preview(row, since):
                preview.append(slim(row))
    preview.sort(key=lambda r: (r['published'] or '', r['id']), reverse=True)
    categories = json.loads(gzip.open(build / 'categories.json.gz', 'rt').read())
    states = report.get('cve_states', {})
    overview = {
        'built': today, 'preview_since': since, 'preview_rule': 'act now (CISA KEV, ENISA exploited or CISA SSVC active), '
        f'plus score >= {CRITICAL:g} published since {since}',
        'totals': {'rows': report['rows'], 'cve': sum(states.values()) + report.get('not_in_cve_list', 0),
                   'published_cve': states.get('PUBLISHED', 0), 'rejected_cve': states.get('REJECTED', 0),
                   'non_cve': report['non_cve_rows'], 'products': report['products'], 'kev': report['with_kev'],
                   'public_exploit': report['with_public_exploit'], 'malicious_packages': report['malicious_packages'],
                   'preview': len(preview), 'sources': len(SOURCES)},
        'by_year': dict(sorted(c['by_year'].items())), 'by_band': dict(sorted(c['by_band'].items())),
        'by_priority': dict(sorted(c['by_priority'].items())), 'by_maturity': dict(sorted(c['by_maturity'].items())),
        'top_classes': [{'name': n, 'total': v} for n, v in sorted(c['classes'].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]],
        'categories': sorted(({'name': name, 'slug': slug(name), 'total': k['total'], 'kev': k['kev'],
                               'public_exploit': k['public_exploit'], 'by_year': dict(sorted(k['by_year'].items())),
                               'top_classes': [n for n, _ in sorted(k['classes'].items(), key=lambda kv: (-kv[1], kv[0]))[:5]],
                               'top_products': [{'product_key': p['product_key'], 'total': p['total'], 'kev': p['kev']}
                                                for p in categories.get(name, [])[:10]],
                               'page': k['total'] >= CATEGORY_MIN}
                              for name, k in cats.items()), key=lambda k: (-k['total'], k['name'])),
        'sources': [{'name': n, 'licence': lic, 'notice': notice, 'url': url} for n, lic, notice, url in SOURCES],
    }
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (('vulnerabilities-preview.json', preview), ('vulnerabilities-overview.json', overview)):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
    return overview


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--build', type=Path, default=ROOT / 'work/vuln-global/build')
    a.add_argument('--out', type=Path, default=ROOT / 'data')
    a.add_argument('--today', default=None, help='build date; default: date of the build file')
    args = a.parse_args()
    today = args.today or datetime.datetime.utcfromtimestamp(
        (args.build / 'vulnerabilities_global.jsonl.gz').stat().st_mtime).date().isoformat()
    print(json.dumps(export(args.build, args.out, today)['totals']))


if __name__ == '__main__':
    main()
