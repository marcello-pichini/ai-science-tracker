"""Build the global vulnerability dataset from the dumps in work/vuln-global/ (see its MANIFEST.tsv).

One row per CVE (cvelistV5 is the canonical list) plus one row per non-CVE vulnerability from allowed OSV
sources. Reuse rules come from docs/vulnerability-sources.md: allowed OSV sources contribute content,
other OSV sources only their advisory ID and link, Chainguard and Minimus nothing, OpenSSF malicious
packages go to a separate table. Scores stay attributed to their source and are never merged.

Outputs (work/vuln-global/build/): vulnerabilities_global.jsonl.gz, malicious_packages.jsonl.gz,
products.json.gz (per product counts) and build_report.json.

Usage: python3 scripts/build_vuln_global.py [--src work/vuln-global] [--out work/vuln-global/build]
"""
import argparse
import collections
import csv
import gzip
import io
import json
import math
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# OSV ID prefix -> (source, license). Vulnerability-level sources: their aliases name the same vulnerability.
VULN_SOURCES = {
    'GHSA': ('GitHub Advisory Database', 'CC-BY-4.0'), 'PYSEC': ('PyPI Advisory Database', 'CC-BY-4.0'),
    'PSF': ('Python Software Foundation', 'CC-BY-4.0'), 'GO': ('Go Vulnerability Database', 'CC-BY-4.0'),
    'RUSTSEC': ('RustSec', 'CC0-1.0'), 'GSD': ('Global Security Database', 'CC0-1.0'),
    'CAN': ('Global Security Database', 'CC0-1.0'), 'OSV': ('OSS-Fuzz', 'CC-BY-4.0'),
    'ASB': ('Android', 'CC-BY-4.0'), 'PUB': ('Android', 'CC-BY-4.0'), 'JLSEC': ('Julia', 'CC-BY-4.0'),
    'DRUPAL': ('Drupal', 'MIT'), 'CURL': ('curl', 'MIT'), 'EEF': ('Erlang Ecosystem Foundation', 'CC-BY-4.0'),
    'OSEC': ('opam', 'CC0-1.0'), 'HSEC': ('Haskell', 'CC0-1.0'), 'RSEC': ('R Consortium', 'Apache-2.0'),
    'V8': ('V8/Chromium', 'Apache-2.0'), 'BIT': ('Bitnami', 'Apache-2.0'),
}
# Advisory-level sources: one advisory may fix many CVEs, so they attach to each CVE and never merge them.
ADVISORY_SOURCES = {
    'RHSA': ('Red Hat', 'CC-BY-4.0'), 'RHBA': ('Red Hat', 'CC-BY-4.0'), 'RHEA': ('Red Hat', 'CC-BY-4.0'),
    'RHLW': ('Red Hat Lightwell', 'CC-BY-4.0'), 'ALSA': ('AlmaLinux', 'MIT'), 'ALBA': ('AlmaLinux', 'MIT'),
    'ALEA': ('AlmaLinux', 'MIT'), 'RLSA': ('Rocky Linux', 'BSD'), 'RXSA': ('Rocky Linux', 'BSD'),
    'AZL': ('Azure Linux', 'MIT'), 'BELL': ('BellSoft', 'MIT'), 'CLEANSTART': ('CleanStart', 'Apache-2.0'),
    'DHI': ('Docker Hardened Images', 'Apache-2.0'),
}
MALICIOUS = {'MAL': ('OpenSSF Malicious Packages', 'Apache-2.0')}
# Dropped entirely: Chainguard (CC BY-NC-ND) and Minimus image-rebuild feeds, and OSV's own CVE copies
# (no stated license; cvelistV5 is the source for CVE content).
SKIP = {'CGA', 'MINI', 'CVE'}
# GSD automated kernel IDs state that impact was never assessed; without a CVE they are not counted.
UNVERIFIED = {'GSD', 'CAN'}
CVE_RE = re.compile(r'^CVE-\d{4}-\d{4,}$')
# Every row has exactly these keys, whatever its origin.
BLANK = {'id': None, 'state': None, 'aliases': [], 'published': None, 'updated': None, 'assigner': None, 'title': None,
         'description': '', 'cwe': [], 'cvss': [], 'severity_label': None, 'affected': [], 'packages': [],
         'nvd_cpe': [], 'nvd_status': None, 'advisories': [], 'kev': None, 'euvd': None, 'epss': None,
         'references': [], 'sources': [],
         'capec': [], 'products': [], 'exploits': [], 'exploit_summary': {}, 'sightings': None,
         'severity': None, 'exposure': None, 'ssvc': None, 'vuln_class': [], 'priority': None, 'remediation': {},
         'credits': [], 'timeline': {}, 'attack_techniques': [], 'summary': None, 'cwe_top25': False,
         'owasp_top10': [], 'fix_commits': [], 'repositories': []}
COMMIT_URL = re.compile(r'^(https?://[^?#]+?)/(?:-/)?commits?/([0-9a-f]{7,40})\b')
KERNEL_COMMIT = re.compile(r'^https?://git\.kernel\.org/.*?(?:/c/|[?&]id=)([0-9a-f]{12,40})\b')
KERNEL_REPO = 'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git'
TOP25_VIEW = '1435'  # 'Weaknesses in the 2025 CWE Top 25 Most Dangerous Software Weaknesses'
OWASP_RE = re.compile(r'^OWASP Top Ten (2021|2025) Category (A\d\d):\d{4} - (.+)$')
TEXT_MAX = 1000
CWE_RE = re.compile(r'^CWE-\d+$')
POC_KEEP = 10  # PoC repositories kept per vulnerability, most starred first; the total is in exploit_summary
DESC_MAX = 2000
NVD_SOURCE = 'NVD (NVD terms of use; not endorsed by NVD)'
EUVD_SOURCE = 'ENISA EUVD (ENISA legal notice)'
EPSS_SOURCE = 'FIRST EPSS (attribution requested)'
MARKUP = re.compile(r'</?(span|b|p|div|font|strong|em|i|br)\b[^>]*>', re.I)  # CNA formatting, e.g. Oracle <span class=font-red>


def prefix(osv_id):
    return osv_id.split('-', 1)[0]


def classify(osv_id):
    p = prefix(osv_id)
    if p in SKIP:
        return 'skip'
    if p in MALICIOUS:
        return 'malicious'
    if p in VULN_SOURCES:
        return 'vuln'
    if p in ADVISORY_SOURCES:
        return 'advisory'
    return 'reference'  # unlicensed or restricted: ID and link only


def source_of(osv_id):
    return VULN_SOURCES.get(prefix(osv_id)) or ADVISORY_SOURCES.get(prefix(osv_id)) or MALICIOUS.get(prefix(osv_id))


def osv_url(osv_id):
    return f'https://osv.dev/vulnerability/{osv_id}'


def osv_packages(rec):
    out = []
    for a in rec.get('affected') or []:
        pkg = a.get('package') or {}
        ranges = [{'type': r.get('type'), 'events': r.get('events')} for r in a.get('ranges') or []
                  if r.get('type') in ('SEMVER', 'ECOSYSTEM')]
        fixed = sorted({e['fixed'] for r in ranges for e in r['events'] or [] if 'fixed' in e})
        git = sorted({(r['repo'], e['fixed']) for r in a.get('ranges') or [] if r.get('type') == 'GIT' and r.get('repo')
                      for e in r.get('events') or [] if 'fixed' in e})
        out.append({'ecosystem': pkg.get('ecosystem'), 'package': pkg.get('name'), 'purl': pkg.get('purl'),
                    'ranges': ranges, 'fixed': fixed, 'git_fixes': [{'repo': r, 'commit': c} for r, c in git],
                    'source': rec['id']})
    return out


def osv_cves(rec, upstream):
    ids = list(rec.get('aliases') or []) + (list(rec.get('upstream') or []) if upstream else [])
    return sorted({i for i in ids if CVE_RE.match(i)})


class OsvIndex:
    """Collects what OSV contributes to each CVE, and the non-CVE vulnerabilities."""

    def __init__(self):
        self.by_cve = collections.defaultdict(lambda: {'aliases': set(), 'packages': [], 'advisories': {}, 'cwe': set(),
                                                       'cvss': []})
        self.non_cve = {}  # id -> record for vulnerability-level records without a CVE alias
        self.malicious = []
        self.counts = collections.Counter()

    def add(self, rec):
        if not re.fullmatch(r'[\w.:+-]+', rec.get('id') or ''):  # e.g. 'SUSE-SU-403 Forbidden-1', an HTTP error saved as a record
            self.counts['bad_id'] += 1
            return
        if rec.get('withdrawn'):
            self.counts['withdrawn'] += 1
            return
        kind = classify(rec['id'])
        self.counts[kind] += 1
        if kind == 'skip':
            return
        if kind == 'malicious':
            name, lic = MALICIOUS[prefix(rec['id'])]
            self.malicious.append({'id': rec['id'], 'aliases': rec.get('aliases') or [],
                                   'published': rec.get('published'), 'modified': rec.get('modified'),
                                   'summary': (rec.get('summary') or rec.get('details') or '')[:DESC_MAX],
                                   'packages': osv_packages(rec), 'source': name, 'license': lic,
                                   'url': osv_url(rec['id'])})
            return
        cves = osv_cves(rec, upstream=kind != 'vuln')
        if kind == 'vuln' and cves:
            self._attach(rec, cves)
            return
        if kind == 'vuln':
            downstream = osv_cves(rec, upstream=True)
            if not downstream:
                if prefix(rec['id']) in UNVERIFIED:
                    self.counts['unverified_without_cve'] += 1
                else:
                    self.non_cve[rec['id']] = rec
                return
            # Downstream advisory (e.g. a Julia JLL wrapping a C library): its package ranges belong to each upstream CVE.
            packages = osv_packages(rec)
            for cve in downstream:
                self.by_cve[cve]['packages'].extend(packages)
            cves = downstream
        # Advisories list many CVEs and packages without a per-CVE mapping, so only the reference is kept.
        src = source_of(rec['id'])
        ref = {'id': rec['id'], 'source': src[0] if src else None, 'license': src[1] if src else None,
               'url': osv_url(rec['id'])}
        for cve in cves:
            self.by_cve[cve]['advisories'][rec['id']] = ref
        if not cves:
            self.counts[f'{kind}_without_cve'] += 1

    def _attach(self, rec, cves):
        packages = osv_packages(rec)
        others = {a for a in rec.get('aliases') or [] if not CVE_RE.match(a)} | {rec['id']}
        for cve in cves:
            slot = self.by_cve[cve]
            slot['aliases'].update(others)
            slot['packages'].extend(packages)
            slot['cwe'].update((rec.get('database_specific') or {}).get('cwe_ids') or [])
            slot['cvss'] += osv_cvss(rec)

    def finalize(self):
        """Attach non-CVE records whose alias (e.g. a GHSA) already belongs to a CVE."""
        owner = collections.defaultdict(set)
        for cve, slot in self.by_cve.items():
            for a in slot['aliases']:
                owner[a].add(cve)
        for i in list(self.non_cve):
            cves = sorted({c for a in [i] + list(self.non_cve[i].get('aliases') or []) for c in owner.get(a, ())})
            if cves:
                self._attach(self.non_cve.pop(i), cves)
                self.counts['non_cve_joined_to_cve'] += 1

    def non_cve_rows(self):
        """Group non-CVE records that alias each other (e.g. PYSEC + GHSA) into one row each."""
        parent = {i: i for i in self.non_cve}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, rec in self.non_cve.items():
            for a in rec.get('aliases') or []:
                if a in parent:
                    parent[find(a)] = find(i)
        groups = collections.defaultdict(list)
        for i in self.non_cve:
            groups[find(i)].append(self.non_cve[i])
        for recs in groups.values():
            ids = sorted(r['id'] for r in recs)
            main = next((i for i in ids if i.startswith('GHSA-')), ids[0])
            first = next(r for r in recs if r['id'] == main)
            yield {**BLANK,
                'id': main, 'state': 'PUBLISHED', 'aliases': sorted(set(ids) - {main}),
                'published': min(filter(None, (r.get('published') for r in recs)), default=None),
                'updated': max(filter(None, (r.get('modified') for r in recs)), default=None),
                'title': first.get('summary'), 'description': (first.get('details') or '')[:DESC_MAX],
                'cwe': sorted({c for r in recs for c in (r.get('database_specific') or {}).get('cwe_ids') or []}),
                'cvss': [c for r in recs for c in osv_cvss(r)],
                'severity_label': (first.get('database_specific') or {}).get('severity'),
                'packages': [p for r in recs for p in osv_packages(r)],
                'references': non_cve_refs(recs),
                'sources': sorted({'%s (%s)' % source_of(r['id']) for r in recs}),
            }


def non_cve_refs(recs):
    refs = collections.OrderedDict()
    for r in recs:
        add_refs(refs, [{'url': x.get('url'), 'tags': [x['type']] if x.get('type') else []}
                        for x in r.get('references') or []], source_of(r['id'])[0])
    return list(refs.values())


def osv_cvss(rec):
    """OSV severity vectors with the base score computed from the vector (v2, v3.x), flagged as computed."""
    out = []
    for sv in rec.get('severity') or []:
        vector = sv.get('score')
        score = cvss_base(vector)
        out.append({'source': source_of(rec['id'])[0], 'version': cvss_version(sv.get('type'), vector),
                    'score': score, 'vector': vector, **({'score_computed': True} if score is not None else {})})
    return out


def roundup(x):
    i = round(x * 100000)
    return i / 100000.0 if i % 10000 == 0 else (i // 10000 + 1) / 10.0


def cvss_base(vector):
    """CVSS v4.0, v3.0/v3.1 and v2 base score from a vector (FIRST specification formulas); None for bad input."""
    if (vector or '').startswith('CVSS:4.0/'):
        return cvss4_base(vector)
    v = dict(x.split(':', 1) for x in (vector or '').strip('()').split('/') if ':' in x)
    try:
        if v.get('CVSS', '').startswith('3'):
            changed = v['S'] == 'C'
            cia = {'H': 0.56, 'L': 0.22, 'N': 0.0}
            iss = 1 - (1 - cia[v['C']]) * (1 - cia[v['I']]) * (1 - cia[v['A']])
            impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
            pr = {'N': 0.85, 'L': 0.68 if changed else 0.62, 'H': 0.5 if changed else 0.27}[v['PR']]
            expl = 8.22 * {'N': 0.85, 'A': 0.62, 'L': 0.55, 'P': 0.2}[v['AV']] * {'L': 0.77, 'H': 0.44}[v['AC']] * pr \
                * {'N': 0.85, 'R': 0.62}[v['UI']]
            if impact <= 0:
                return 0.0
            return roundup(min(1.08 * (impact + expl), 10)) if changed else roundup(min(impact + expl, 10))
        if 'Au' in v and 'CVSS' not in v:
            cia = {'N': 0.0, 'P': 0.275, 'C': 0.660}
            impact = 10.41 * (1 - (1 - cia[v['C']]) * (1 - cia[v['I']]) * (1 - cia[v['A']]))
            expl = 20 * {'L': 0.395, 'A': 0.646, 'N': 1.0}[v['AV']] * {'H': 0.35, 'M': 0.61, 'L': 0.71}[v['AC']] \
                * {'M': 0.45, 'S': 0.56, 'N': 0.704}[v['Au']]
            return round((0.6 * impact + 0.4 * expl - 1.5) * (0 if impact == 0 else 1.176), 1)
    except KeyError:
        return None
    return None


CVSS4 = json.loads((Path(__file__).resolve().parent / 'cvss4_data.json').read_text())
CVSS4_LEVELS = {'AV': {'N': 0.0, 'A': 0.1, 'L': 0.2, 'P': 0.3}, 'PR': {'N': 0.0, 'L': 0.1, 'H': 0.2},
                'UI': {'N': 0.0, 'P': 0.1, 'A': 0.2}, 'AC': {'L': 0.0, 'H': 0.1}, 'AT': {'N': 0.0, 'P': 0.1},
                'VC': {'H': 0.0, 'L': 0.1, 'N': 0.2}, 'VI': {'H': 0.0, 'L': 0.1, 'N': 0.2},
                'VA': {'H': 0.0, 'L': 0.1, 'N': 0.2}, 'SC': {'H': 0.1, 'L': 0.2, 'N': 0.3},
                'SI': {'S': 0.0, 'H': 0.1, 'L': 0.2, 'N': 0.3}, 'SA': {'S': 0.0, 'H': 0.1, 'L': 0.2, 'N': 0.3},
                'CR': {'H': 0.0, 'M': 0.1, 'L': 0.2}, 'IR': {'H': 0.0, 'M': 0.1, 'L': 0.2},
                'AR': {'H': 0.0, 'M': 0.1, 'L': 0.2}}
CVSS4_BASE = ('AV', 'AC', 'AT', 'PR', 'UI', 'VC', 'VI', 'VA', 'SC', 'SI', 'SA')


def cvss4_base(vector):
    """CVSS v4.0 score from a vector, ported from FIRST's reference calculator (cvss_score.js, same float steps)."""
    try:
        sel = dict(p.split(':', 1) for p in vector.rstrip('/').split('/')[1:])
    except ValueError:
        return None
    if not vector.startswith('CVSS:4.0/') or any(k not in sel for k in CVSS4_BASE):
        return None

    def m(k):
        v = sel.get(k, 'X')
        if k == 'E' and v == 'X':
            return 'A'
        if k in ('CR', 'IR', 'AR') and v == 'X':
            return 'H'
        if sel.get('M' + k, 'X') != 'X':
            return sel['M' + k]
        return v

    if any(k not in CVSS4_LEVELS or m(k) not in CVSS4_LEVELS[k] for k in CVSS4_BASE):
        return None
    if all(m(k) == 'N' for k in ('VC', 'VI', 'VA', 'SC', 'SI', 'SA')):
        return 0.0
    av, pr, ui = m('AV'), m('PR'), m('UI')
    eq1 = 0 if av == pr == ui == 'N' else 1 if (av == 'N' or pr == 'N' or ui == 'N') and av != 'P' else 2
    eq2 = 0 if m('AC') == 'L' and m('AT') == 'N' else 1
    vc, vi, va = m('VC'), m('VI'), m('VA')
    eq3 = 0 if vc == vi == 'H' else 1 if 'H' in (vc, vi, va) else 2
    eq4 = 0 if m('MSI') == 'S' or m('MSA') == 'S' else 1 if 'H' in (m('SC'), m('SI'), m('SA')) else 2
    eq5 = {'A': 0, 'P': 1, 'U': 2}.get(m('E'))
    if eq5 is None:
        return None
    eq6 = 0 if (m('CR') == 'H' and vc == 'H') or (m('IR') == 'H' and vi == 'H') or (m('AR') == 'H' and va == 'H') else 1
    lookup = CVSS4['lookup']
    macro = f'{eq1}{eq2}{eq3}{eq4}{eq5}{eq6}'
    value = lookup.get(macro)
    if value is None:
        return None

    def at(*eq):
        return lookup.get(''.join(map(str, eq)))

    if eq3 == 0 and eq6 == 0:
        left, right = at(eq1, eq2, eq3, eq4, eq5, eq6 + 1), at(eq1, eq2, eq3 + 1, eq4, eq5, eq6)
        lower36 = left if left is not None and right is not None and left > right else right  # as the JS compares
    elif eq3 == 1 and eq6 == 0:
        lower36 = at(eq1, eq2, eq3, eq4, eq5, eq6 + 1)
    elif eq6 == 1 and eq3 in (0, 1):
        lower36 = at(eq1, eq2, eq3 + 1, eq4, eq5, eq6)
    else:
        lower36 = at(eq1, eq2, eq3 + 1, eq4, eq5, eq6 + 1)
    lower = [at(eq1 + 1, eq2, eq3, eq4, eq5, eq6), at(eq1, eq2 + 1, eq3, eq4, eq5, eq6), lower36,
             at(eq1, eq2, eq3, eq4 + 1, eq5, eq6), at(eq1, eq2, eq3, eq4, eq5 + 1, eq6)]
    mc = CVSS4['max_composed']
    dist = {}
    for a in mc['eq1'][str(eq1)]:
        for b in mc['eq2'][str(eq2)]:
            for c in mc['eq3'][str(eq3)][str(eq6)]:
                for d in mc['eq4'][str(eq4)]:
                    for e in mc['eq5'][str(eq5)]:
                        mx = dict(p.split(':') for p in (a + b + c + d + e).strip('/').split('/'))
                        dist = {k: CVSS4_LEVELS[k][m(k)] - CVSS4_LEVELS[k][mx[k]] for k in CVSS4_LEVELS}
                        if all(v >= 0 for v in dist.values()):
                            break
                    else:
                        continue
                    break
                else:
                    continue
                break
            else:
                continue
            break
        else:
            continue
        break
    current = [dist['AV'] + dist['PR'] + dist['UI'], dist['AC'] + dist['AT'],
               dist['VC'] + dist['VI'] + dist['VA'] + dist['CR'] + dist['IR'] + dist['AR'],
               dist['SC'] + dist['SI'] + dist['SA'], 0]
    ms = CVSS4['max_severity']
    max_sev = [ms['eq1'][str(eq1)] * 0.1, ms['eq2'][str(eq2)] * 0.1, ms['eq3eq6'][str(eq3)][str(eq6)] * 0.1,
               ms['eq4'][str(eq4)] * 0.1, None]
    total, n = 0, 0
    for i, low in enumerate(lower):
        if low is None:
            continue
        n += 1
        total += (value - low) * (current[i] / max_sev[i] if i < 4 else 0)
    value -= total / n if n else 0
    value = min(max(value, 0.0), 10.0)
    return math.floor(value * 10 + 0.5) / 10  # JS Math.round


def cvss_version(osv_type, vector):
    m = re.match(r'CVSS:(\d\.\d)/', vector or '')
    return m[1] if m else {'CVSS_V2': '2.0', 'CVSS_V3': '3.x', 'CVSS_V4': '4.0'}.get(osv_type, osv_type)


def cvss_from_metrics(metrics, source):
    out = []
    for m in metrics or []:
        for key in ('cvssV4_0', 'cvssV3_1', 'cvssV3_0', 'cvssV2_0'):
            if key in m and isinstance(m[key], dict):
                c = m[key]
                out.append({'source': source, 'version': c.get('version'), 'score': c.get('baseScore'),
                            'vector': c.get('vectorString')})
    return out


def cna_affected(cna, source=None):
    out = []
    for a in cna.get('affected') or []:
        out.append({k: a[k] for k in ('vendor', 'product', 'packageName', 'packageURL', 'collectionURL', 'repo',
                                          'cpes', 'defaultStatus')
                    if a.get(k)} | {'source': source} | {'versions': [{k: v[k] for k in ('version', 'lessThan', 'lessThanOrEqual',
                                                                     'versionType', 'status') if k in v}
                                                 for v in a.get('versions') or []]})
    return out


def en_texts(items):
    """English 'value' strings of a CVE text list (solutions, workarounds...), trimmed, at most 5."""
    return [re.sub(r'\s+', ' ', d['value']).strip()[:TEXT_MAX] for d in items or []
            if d.get('value') and (d.get('lang') or 'en').startswith('en')][:5]


def problem_cwes(container):
    return {d['cweId'] for p in container.get('problemTypes') or [] for d in p.get('descriptions') or []
            if CWE_RE.match(d.get('cweId') or '')}


def clean_url(url):
    """Repair common typos in source URLs ('ttps://', 'https:/host', 'ZDI-CAN-1https://…'); None if no URL is left."""
    url = (url or '').strip()
    m = re.search(r'(https?|ftp):/+|\bttps?://', url)
    if not m:  # 'github.com/coredns/coredns' gets a scheme; a bare 'owner/repo' is no URL
        return 'https://' + url if re.match(r'^[\w-]+(\.[\w-]+)*\.[a-z]{2,}/\S*$', url) else None
    url = url[m.start():]
    url = re.sub(r'^ttp', 'http', url)
    return re.sub(r'^(https?|ftp):/+', r'\1://', url)


def add_refs(refs, items, source):
    """Merge reference URLs from several containers, keeping each URL once with the union of its tags."""
    for r in items or []:
        url = clean_url(r.get('url'))
        if not url:
            continue
        slot = refs.setdefault(url, {'url': url, 'tags': [], 'sources': []})
        slot['tags'] = sorted(set(slot['tags']) | set(r.get('tags') or []))
        if source not in slot['sources']:
            slot['sources'].append(source)


def cve_row(rec, extra):
    meta = rec['cveMetadata']
    cve = meta['cveId']
    cna = rec.get('containers', {}).get('cna', {})
    desc = next((d['value'] for d in cna.get('descriptions') or [] if d.get('lang', '').startswith('en')),
                (cna.get('rejectedReasons') or [{}])[0].get('value', ''))
    assigner = meta.get('assignerShortName') or 'CNA'
    cvss = cvss_from_metrics(cna.get('metrics'), assigner)
    affected = cna_affected(cna, assigner)
    cwe = problem_cwes(cna)
    refs = collections.OrderedDict()
    add_refs(refs, cna.get('references'), assigner)
    for adp in rec.get('containers', {}).get('adp') or []:
        name = (adp.get('providerMetadata') or {}).get('shortName') or 'ADP'
        cvss += cvss_from_metrics(adp.get('metrics'), name)
        affected += cna_affected(adp, name)
        cwe |= problem_cwes(adp)
        add_refs(refs, adp.get('references'), name)
    nvd = extra['nvd'].get(cve) or {}
    cvss += nvd.get('cvss', [])
    cwe |= set(nvd.get('cwe', []))
    add_refs(refs, nvd.get('references'), 'NVD')
    cvss = list({(c['source'], c['version'], c['score'], c['vector']): c for c in cvss}.values())
    osv = extra['osv'].by_cve.get(cve) or {'aliases': set(), 'packages': [], 'advisories': {}, 'cwe': set(), 'cvss': []}
    cwe |= osv['cwe']
    cvss = list({(c['source'], c['version'], c['score'], c['vector']): c for c in cvss + osv['cvss']}.values())
    euvd = extra['euvd'].get(cve)
    other = extra.get('other') or {}
    aliases = set(osv['aliases']) | ({euvd['id']} if euvd else set()) | set((other.get('aliases') or {}).get(cve, ()))
    other_refs = list(((other.get('refs') or {}).get(cve) or {}).values())
    sources = {'CVE List (MITRE CVE terms)'} | ({NVD_SOURCE} if nvd else set())
    sources |= {'%s (%s)' % source_of(a) for a in aliases if source_of(a)}
    sources |= {'%s (%s)' % (v['source'], v['license']) for v in osv['advisories'].values() if v['source']}
    sources |= {'%s (%s)' % (v['source'], v['license']) for v in other_refs}
    if euvd:
        sources.add(EUVD_SOURCE)
    if cve in extra['kev']:
        sources.add('CISA KEV (CC0-1.0)')
    if cve in extra['epss']:
        sources.add(EPSS_SOURCE)
    ssvc = None
    for adp in rec.get('containers', {}).get('adp') or []:
        for m in adp.get('metrics') or []:
            o = m.get('other') or {}
            if o.get('type') == 'ssvc':
                opts = {k: v for d in (o.get('content') or {}).get('options') or [] for k, v in d.items()}
                ssvc = {'exploitation': opts.get('Exploitation'), 'automatable': opts.get('Automatable'),
                        'technical_impact': opts.get('Technical Impact'),
                        'date': ((o.get('content') or {}).get('timestamp') or '')[:10] or None,
                        'source': (adp.get('providerMetadata') or {}).get('shortName') or 'ADP'}
    remediation = {k: en_texts(cna.get(k)) for k in ('solutions', 'workarounds')}
    remediation['vendor_exploitation_statement'] = en_texts(cna.get('exploits'))
    credits = [{'type': c.get('type'), 'name': c.get('value')} for c in cna.get('credits') or []
               if c.get('value') and (c.get('lang') or 'en').startswith('en')][:20]
    timeline = {'reserved': meta.get('dateReserved'), 'public': cna.get('datePublic'),
                'events': [{'date': t.get('time'), 'event': t.get('value')} for t in cna.get('timeline') or []
                           if (t.get('lang') or 'en').startswith('en')][:20]}
    return {**BLANK, 'ssvc': ssvc, 'remediation': remediation, 'credits': credits, 'timeline': timeline,
        'id': cve, 'state': meta.get('state'), 'aliases': sorted(aliases),
        'published': meta.get('datePublished'), 'updated': meta.get('dateUpdated'),
        'assigner': meta.get('assignerShortName'), 'title': cna.get('title'), 'description': desc[:DESC_MAX],
        'cwe': sorted(cwe),
        'capec': sorted({i['capecId'] for i in cna.get('impacts') or [] if i.get('capecId')}),
        'cvss': cvss, 'affected': affected, 'packages': osv['packages'], 'nvd_cpe': nvd.get('cpe', []),
        'nvd_status': nvd.get('status'), 'advisories': sorted(list(osv['advisories'].values()) + other_refs, key=lambda a: a['id'] or ''),
        'kev': extra['kev'].get(cve), 'euvd': euvd, 'epss': extra['epss'].get(cve),
        'references': list(refs.values()),
        'sources': sorted(sources),
    }


def max_score(row):
    scores = [c['score'] for c in row['cvss'] if isinstance(c.get('score'), (int, float))]
    return max(scores) if scores else None


def band(score):
    if score is None:
        return 'unscored'
    return 'critical' if score >= 9 else 'high' if score >= 7 else 'medium' if score >= 4 else 'low' if score > 0 else 'none'


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


FAMILY_ALIASES = {'linux:linux': 'linux:kernel', 'linux:linux kernel': 'linux:kernel', ':android': 'google:android',
                  ':linux kernel': 'linux:kernel'}
CORP_SUFFIX = re.compile(r'[,\s]+(inc|corp|corporation|co|ltd|limited|llc|gmbh|ag|s\.?a|plc|l\.?p)\.?$')
VENDOR_SUFFIX = re.compile(r'\s+(software foundation|foundation|global development group|development group|project|team|software|'
                           r'labs|technologies|technology|communications|solutions)$|\.(com|org|net|io|us)$')
EDITION_SUFFIX = re.compile(r'(\s+for\s+.*(systems|editions?)|,\s*[^,]*\bedition|\s+(service pack|sp)\s*\d*|[,;:\s]+)$')


def strip_parens(t):
    """Drop parenthesised text, nested ('otrs (( otrs )) community edition') or unclosed ('esm (when fusion')."""
    while True:
        shorter = re.sub(r'\s*\([^()]*\)', '', t)
        if shorter == t:
            break
        t = shorter
    return re.sub(r'\s+', ' ', re.sub(r'\s*\(.*$', '', t).replace(')', ' ')).strip()


def family(key):
    """Collapse editions of one product: 'microsoft:windows 10 version 1809 for x64-based systems' -> 'microsoft:windows'.

    shortcut: heuristic suffix rules plus a small alias map; a curated product map should replace it for comparisons.
    """
    vendor, _, product = key.partition(':')
    vendor = re.sub(r'^the\s+', '', vendor)
    while True:
        shorter = VENDOR_SUFFIX.sub('', CORP_SUFFIX.sub('', vendor))
        if shorter == vendor:
            break
        vendor = shorter
    product = strip_parens(product) or product
    product = re.sub(r'\s+(prior to|before|through|up to|<=?)\s+\d.*$', '', product) or product  # 'chrome prior to 22'
    if vendor and product.startswith(vendor + ' '):  # 'apache:apache http server' -> 'apache:http server'
        product = product[len(vendor) + 1:]
    while True:
        shorter = EDITION_SUFFIX.sub('', product)
        shorter = re.sub(r'\s+(version|v|r|release)?\s*\d[\w.]*$', '', shorter)
        if shorter == product or not shorter:
            break
        product = shorter
    vendor, product = norm(vendor), norm(re.sub(r'\s+,', ',', product))  # 'pc 3000 , cpg bios' -> 'pc 3000, cpg bios'
    key = FAMILY_ALIASES.get(f'{vendor}:{product}', f'{vendor}:{product}')
    return canonical(key)


PRODUCT_MAP = json.loads((Path(__file__).resolve().parent / 'vuln_product_map.json').read_text())
PREFIXES = {v: sorted(p, key=len, reverse=True) for v, p in PRODUCT_MAP['product_prefixes'].items()}
VENDORLESS = [(re.compile(rx), v) for rx, v in PRODUCT_MAP.get('vendorless_rules', {}).items()]
CATEGORY = {key: cat for cat, keys in PRODUCT_MAP['categories'].items() for key in keys}


def category_of(key):
    """Exact curated category, else the first matching rule (vendor, product prefix or suffix), else None."""
    if key in CATEGORY:
        return CATEGORY[key]
    vendor, _, product = key.partition(':')
    for rule in PRODUCT_MAP.get('category_rules', ()):
        if 'vendor' in rule and vendor not in rule['vendor']:
            continue
        pre, suf = rule.get('product_prefix'), rule.get('product_suffix')
        if pre and not any(product.startswith(x) for x in pre) and not (suf and any(product.endswith(x) for x in suf)):
            continue
        if suf and not pre and not any(product.endswith(x) for x in suf):
            continue
        return rule['category']
    return None


def canonical(key):
    """Apply the curated map (scripts/vuln_product_map.json): vendor renames, edition prefixes, product renames."""
    vendor, _, product = key.partition(':')
    vendor = PRODUCT_MAP['vendor_aliases'].get(vendor, vendor)
    for pref in PREFIXES.get(vendor, ()):
        if product == pref or product.startswith(pref + ' '):
            product = pref
            break
    key = f'{vendor}:{product}'
    return PRODUCT_MAP['aliases'].get(key, key)


NA = ('', 'n/a', 'unknown', '-', '*', 'placeholder')


def row_products(row):
    """Every product a row names, from the CNA/ADP affected lists, NVD CPE matches and OSV packages, one entry per
    product family with where it came from and the fixed versions the sources state."""
    out = {}

    def add(vendor, product, source, cpe=None, purl=None, ecosystem=None, fixed=(), ranges=()):
        vendor, product = norm(vendor), norm(product)
        if not ecosystem:  # package names are exact; vendor/product names come in CPE spelling too
            vendor, product = vendor.replace('_', ' ').replace(':', ' '), product.replace('_', ' ')
            repo = re.match(r'https?://(?:www\.)?(?:github|gitlab)\.com/([^/\s]+)/([^/\s#?]+)', product)
            if repo:  # a repository URL given as the product name
                vendor, product = (vendor if vendor not in NA else repo[1]), repo[2].removesuffix('.git')
            # 'adobe flash player 24.0.0.194 and earlier.' -> 'adobe flash player'; a bare version is no product
            product = re.sub(r'\s*\bv?\d[\w.]*\s+and\s+(earlier|prior)\b.*$', '', product).strip(' .,;-')
            vendor, product = norm(vendor), norm(product)
        if product in NA:
            return
        # Commas inside parentheses ('big-ip (ltm, aam, afm)') list editions of one product, not products.
        outer = strip_parens(product)
        if not ecosystem and not re.search(r'[a-z0-9]', outer) and re.search(r'[a-z0-9]', product):
            outer = re.sub(r'[()]', ',', product)  # '(lgpcsuite setup), (ipsfullhd, lg ultrawide)': the names are inside
        # One comma usually belongs to the name ('windows server, version 1903'); 'redmi k40 ,redmi note10 pro' does not.
        if not ecosystem and (';' in outer or re.search(r'\S ,\S', outer) or (outer.count(',') >= 2 and
                                               all(len(x.strip()) <= 40 for x in outer.split(',')))):
            # One CNA entry naming several products ('ap2000;ips module;ngfw module'): one family each.
            for part in re.split(r'[;,]', outer):
                if part.strip():
                    add(vendor, part.strip(), source, cpe, purl, ecosystem, fixed, ranges)
            return
        vendor = '' if vendor in NA else vendor
        key = family(f'{vendor}:{product}')
        p = out.setdefault(key, {'product_key': key, 'names': set(), 'sources': set(), 'types': set(), 'cpe': set(),
                                 'purl': set(), 'ecosystems': set(), 'fixed': set(), 'fixed_commits': set(),
                                 'ranges': [], 'exact': {}})
        p['names'].add(f'{vendor}:{product}')
        p['sources'].add(source)
        for field, value in (('cpe', cpe), ('purl', purl), ('ecosystems', ecosystem)):
            if value:
                p[field].add(value)
        part = cpe.split(':')[2] if cpe and cpe.count(':') >= 2 else None
        p['types'].add(CPE_PART.get(part) or ('package' if ecosystem else None))
        p['types'].discard(None)
        for f in (x for v in fixed for x in re.split(r'[,\n]+', v or '')):
            f = fixed_version(f)
            if f:
                (p['fixed_commits'] if HEX_SHA.match(f) else p['fixed']).add(f)
        for r in ranges:
            r = {'source': source, **{k: v for k, v in r.items() if v not in (None, '')}}
            if set(r) <= {'source', 'status', 'type', 'version'} and 'version' in r:
                # Exact versions (Cisco lists thousands) are grouped, so none is lost to the range cap.
                group = p['exact'].setdefault((r['source'], r.get('status'), r.get('type')), [])
                if r['version'] not in group and len(group) < EXACT_MAX:
                    group.append(r['version'])
            elif len(p['ranges']) < RANGES_MAX and r not in p['ranges']:
                p['ranges'].append(r)

    for a in row['affected']:
        # A fix is the upper bound of an affected range, or an exact version the CNA marks unaffected (e.g. 22.7R2.5).
        fixed = [v.get('lessThan') for v in a.get('versions') or [] if v.get('status') == 'affected']
        fixed += [v.get('version') for v in a.get('versions') or [] if v.get('status') == 'unaffected'
                  and not v.get('lessThan') and not v.get('lessThanOrEqual') and v.get('version') not in ('0', '*')]
        cpes = a.get('cpes') or []
        add(a.get('vendor'), a.get('product') or a.get('packageName'), a.get('source') or 'CNA',
            cpe=cpe_base(cpes[0]) if cpes else None, purl=a.get('packageURL'), fixed=fixed,
            ranges=cna_ranges(a))
        for c in cpes[1:]:
            parts = c.split(':')
            if len(parts) > 4:
                add(parts[3].replace('_', ' '), parts[4].replace('_', ' '), a.get('source') or 'CNA', cpe=cpe_base(c))
    for m in row['nvd_cpe']:
        parts = m.get('criteria', '').split(':')
        if len(parts) > 4:
            exact = parts[5] if len(parts) > 5 and parts[5] not in ('*', '-') else None
            add(parts[3].replace('_', ' '), parts[4].replace('_', ' '), 'NVD', cpe=cpe_base(m['criteria']),
                fixed=[m.get('versionEndExcluding')],
                ranges=[{'status': 'affected', 'version': exact,
                         'introduced': m.get('versionStartIncluding'), 'introduced_after': m.get('versionStartExcluding'),
                         'fixed': m.get('versionEndExcluding'), 'last_affected': m.get('versionEndIncluding'),
                         'any_version': not exact and not any(k.startswith('version') for k in m) or None}])
    for pk in row['packages']:
        add(pk.get('ecosystem'), pk.get('package'), pk.get('source') or 'OSV', purl=pk.get('purl'),
            ecosystem=pk.get('ecosystem'), fixed=pk.get('fixed') or [], ranges=osv_ranges(pk))
    owner = (row.get('assigner') or '').lower().replace('_', ' ').replace('-', ' ')
    vendors = {k.split(':', 1)[0] for k in out if not k.startswith(':')}
    match = next((v for v in sorted(vendors) if owner and owner in (v, v.replace(' ', ''))), None)
    for key in [k for k in out if k.startswith(':')]:
        product = key[1:]
        target = next((k for k in out if not k.startswith(':') and k.split(':', 1)[1] == product), None)
        if not target and match:
            target = family(f'{match}:{product}')
        if not target:
            owner_vendor = next((v for rx, v in VENDORLESS if rx.match(product)), None)
            target = family(f'{owner_vendor}:{product}') if owner_vendor else None
        if target:
            p = out.pop(key)
            t = out.setdefault(target, {**p, 'product_key': target, **{f: set() for f in p if isinstance(p[f], set)},
                                        'ranges': [], 'exact': {}})
            for f, v in p.items():
                if isinstance(v, set):
                    t[f] |= v
            t['ranges'] += [r for r in p['ranges'] if r not in t['ranges']][:max(0, RANGES_MAX - len(t['ranges']))]
            for g, vs in p['exact'].items():
                t['exact'].setdefault(g, []).extend(v for v in vs if v not in t['exact'].get(g, []))
    result = []
    for key, p in sorted(out.items()):
        exact = p.pop('exact')
        p['ranges'] += [{k: v for k, v in (('source', src), ('status', status), ('type', typ), ('versions', vs)) if v}
                        for (src, status, typ), vs in exact.items()]
        result.append({**{k: sorted(v) if isinstance(v, set) else v for k, v in p.items()}, 'category': category_of(key),
                       'lifecycle': (LIFECYCLE.get(key) or {}).get('id')})
    return result


LIFECYCLE = {}  # product_key -> endoflife.date lifecycle; filled by main() before the build
RANGES_MAX = 100  # range entries per product and row; the raw affected/nvd_cpe/packages lists keep everything
EXACT_MAX = 5000  # exact versions per product, source and status
PLACEHOLDER = {'n/a', 'na', 'unknown', 'unspecified', 'none', 'latest', '0', '*', '-', 'all', 'various', 'see advisory'}
HEX_SHA = re.compile(r'^[0-9a-f]{12,40}$')


def fixed_version(f):
    """'macOS Mojave 10.14.5' -> '10.14.5'; placeholders and words without a digit ('publication') -> None."""
    f = (f or '').strip()
    if f.lower() in PLACEHOLDER or '*' in f or '://' in f or not re.search(r'\d', f):  # 'log4j-core*' is a pattern, not a fix
        return None
    if ' ' in f:
        tokens = [t for t in f.split() if re.match(r'^v?\d[\w.+~:-]*$', t)]
        return tokens[-1] if tokens else None
    if len(f) > 40:  # 'amd-software-adrenalin-edition-25.5.1-minimalsetup-250513_web.exe' -> '25.5.1'
        m = re.search(r'\d+(\.\d+)+', f)
        return m[0] if m else None
    return f


def cna_ranges(a):
    """CVE 5 'versions' -> uniform ranges: introduced/fixed/last_affected or one exact version, with status."""
    out = []
    for v in a.get('versions') or []:
        start = v.get('version')
        start = None if start in ('0', '*', 'n/a', 'unspecified') else start
        if v.get('lessThan') or v.get('lessThanOrEqual'):
            out.append({'status': v.get('status'), 'type': v.get('versionType'), 'introduced': start,
                        'fixed': v.get('lessThan') if v.get('lessThan') not in ('*',) else None,
                        'last_affected': v.get('lessThanOrEqual') if v.get('lessThanOrEqual') not in ('*',) else None,
                        'any_version': (v.get('lessThan') == '*' or v.get('lessThanOrEqual') == '*') or None})
        elif start:
            out.append({'status': v.get('status'), 'type': v.get('versionType'), 'version': start})
    if not out and a.get('defaultStatus') == 'affected':
        out.append({'status': 'affected', 'any_version': True})
    return out


def osv_ranges(pk):
    """OSV events (introduced, fixed, last_affected, limit) -> one range per introduced event."""
    out = []
    for r in pk.get('ranges') or []:
        cur = None
        for e in r.get('events') or []:
            if 'introduced' in e:
                cur = {'status': 'affected', 'type': (r.get('type') or '').lower(),
                       'introduced': None if e['introduced'] == '0' else e['introduced']}
                out.append(cur)
            elif cur is not None:
                for k in ('fixed', 'last_affected', 'limit'):
                    if k in e:
                        cur[k] = e[k]
    for cur in out:
        if not ({'introduced', 'fixed', 'last_affected', 'limit'} & {k for k, v in cur.items() if v}):
            cur['any_version'] = True  # introduced 0 and no fix event: every version
    return out


CPE_PART = {'a': 'application', 'o': 'operating system', 'h': 'hardware'}


def cpe_base(cpe):
    """'cpe:2.3:a:apache:http_server:2.4.1:*:...' -> 'cpe:2.3:a:apache:http_server' (product level, no version)."""
    return ':'.join(cpe.split(':')[:5])


def enrich(row, extra):
    """Attach what every row links to: weakness names, attack patterns, products and public exploits."""
    cwes, capecs = extra.get('cwe') or {}, extra.get('capec') or {}
    for k in ('title', 'description'):
        if row[k]:
            text = MARKUP.sub('', row[k]) if re.search(r'</(span|b|p|div|font)>', row[k], re.I) else row[k]
            row[k] = text.strip() or None
    row['cvss'] = list({json.dumps(c, sort_keys=True): c for c in row['cvss']}.values())
    for c in row['cvss']:
        if c.get('score') is None and c.get('vector'):
            c['score'] = cvss_base(c['vector'])
            if c['score'] is not None:
                c['score_computed'] = True
        elif c.get('score') is not None and c.get('vector'):
            # A published score that its own vector does not give (a source error, or v4 threat metrics left out).
            vec = c['vector']
            if vec.startswith('CVSS:4.0/'):
                vec = '/'.join(['CVSS:4.0'] + [x for x in vec.rstrip('/').split('/')[1:] if x.split(':')[0] in CVSS4_BASE])
            calc = cvss_base(vec)
            if calc is not None and abs(calc - c['score']) > 0.05:
                c['vector_score'] = calc
    ids = sorted({c if isinstance(c, str) else c['id'] for c in row['cwe']}, key=id_num)
    row['cwe'] = [{'id': c, 'name': (cwes.get(c) or {}).get('name')} for c in ids]
    capec = {c: 'CNA' for c in row['capec'] if isinstance(c, str)}
    for c in ids:
        for a in (cwes.get(c) or {}).get('capec', []):
            capec.setdefault(a, c)
    row['capec'] = [{'id': a, 'name': capecs.get(a), 'via': via} for a, via in sorted(capec.items(), key=lambda kv: id_num(kv[0]))]
    row['products'] = row_products(row)
    found, counts = [], collections.Counter()
    for key in [row['id']] + [a for a in row['aliases'] if CVE_RE.match(a)]:
        hit = (extra.get('exploits') or {}).get(key)
        if hit:
            found += hit['items']
            counts |= hit['counts']  # an alias CVE often lists the same exploits: max, not sum
    unique = {}
    for x in found:
        unique.setdefault((x['source'], x['id']), x)
    row['exploits'] = list(unique.values())
    summary = {k: counts.get(k, 0) for k in EXPLOIT_SOURCES}
    summary['kev'] = row['kev'] is not None
    summary['euvd_exploited'] = bool(row['euvd'] and row['euvd'].get('exploited_since'))
    summary['public_exploit'] = any(summary[k] for k in EXPLOIT_SOURCES)
    summary['ransomware'] = (row['kev'] or {}).get('ransomware') == 'Known'
    sightings = extra.get('sightings') or {}
    row['sightings'] = next((sightings[k] for k in [row['id']] + row['aliases'] if k in sightings), None)
    seen = (row['sightings'] or {}).get('counts') or {}
    summary['sightings_exploited'] = seen.get('exploited', 0) + seen.get('confirmed', 0)
    summary['sightings_poc'] = seen.get('published-proof-of-concept', 0)
    ssvc_exp = (row['ssvc'] or {}).get('exploitation')
    summary['maturity'] = ('exploited in the wild' if summary['kev'] or summary['euvd_exploited'] or ssvc_exp == 'active'
                           else 'weaponized' if summary['metasploit']
                           else 'proof of concept' if summary['exploitdb'] or summary['poc_github'] or ssvc_exp == 'poc'
                           else 'detection template' if summary['nuclei'] else 'none known')
    row['exploit_summary'] = summary
    main = primary_cvss(row)
    row['severity'] = main and {'score': main['score'], 'band': band(main['score']), 'version': main['version'],
                                'source': main['source'], 'max_score': max_score(row)}
    with_vector = ([main] if main and main.get('vector') else []) + [c for c in row['cvss'] if c.get('vector')]
    exposure = next((parse_vector(c['vector']) for c in with_vector if parse_vector(c['vector'])), None)
    if exposure:
        src = next(c for c in with_vector if parse_vector(c['vector']))
        exposure.update(source=src['source'], version=src['version'])
    row['exposure'] = exposure
    row['vuln_class'] = sorted({c for c in (cwe_class(x['id'], cwes) for x in row['cwe']) if c})
    row['cwe_top25'] = any((cwes.get(x['id']) or {}).get('top25') for x in row['cwe'])
    row['owasp_top10'] = sorted({o for x in row['cwe'] for o in (cwes.get(x['id']) or {}).get('owasp', ())})
    tags = lambda r: {t.lower().replace(' ', '-') for t in r['tags']}
    rem = dict(row['remediation'] or {})
    rem['fixed_versions'] = {p['product_key']: p['fixed'] for p in row['products'] if p['fixed']}
    rem['patch_urls'] = [r['url'] for r in row['references'] if 'patch' in tags(r)][:20]
    rem['vendor_advisory_urls'] = [r['url'] for r in row['references'] if tags(r) & {'vendor-advisory'}][:20]
    commits = fix_commits(row)
    row['fix_commits'] = commits
    row['repositories'] = repositories(row, commits)
    rem['has_documented_fix'] = bool(rem['fixed_versions'] or rem['patch_urls'] or rem.get('solutions') or commits)
    if row['kev']:
        rem['cisa_required_action'] = row['kev'].get('required_action')
    row['remediation'] = rem
    tl = dict(row['timeline'] or {})
    tl['published'] = row['published']
    tl['kev_added'] = (row['kev'] or {}).get('date_added')
    tl['kev_due'] = (row['kev'] or {}).get('due_date')
    tl['euvd_exploited_since'] = (row['euvd'] or {}).get('exploited_since')
    # Metasploit's date is the vulnerability's disclosure date, not the module's, so it is left out here.
    tl['first_public_exploit'] = min((x['date'] for x in row['exploits'] if x.get('date')
                                      and x['source'] != 'Metasploit'), default=None)
    tl['first_sighting'] = (row['sightings'] or {}).get('first')
    tl['days_to_kev'] = days_between(row['published'], tl['kev_added'])
    tl['days_to_first_public_exploit'] = days_between(row['published'], tl['first_public_exploit'])
    row['timeline'] = tl
    row['priority'] = priority(row)
    techniques = {}
    for c in row['capec']:
        for t in (extra.get('capec_attack') or {}).get(c['id'], ()):
            techniques.setdefault(t['id'], {**t, 'via': c['id']})
    row['attack_techniques'] = [techniques[k] for k in sorted(techniques)]
    row['summary'] = summary_line(row)
    return row


def days_between(a, b):
    import datetime
    try:
        return (datetime.date.fromisoformat(b[:10]) - datetime.date.fromisoformat(a[:10])).days
    except (TypeError, ValueError):
        return None


def norm_repo(url):
    url = (url or '').strip().rstrip('/')
    url = re.sub(r'\.git$', '', url)
    return re.sub(r'^(http|git)://', 'https://', url)


def fix_commits(row):
    """Commits that fix the vulnerability: commit links in the references, CNA git ranges, OSV GIT ranges."""
    out = {}
    for r in row['references']:
        m = KERNEL_COMMIT.match(r['url'])
        if m:
            out.setdefault(m[1], {'repo': KERNEL_REPO, 'commit': m[1], 'url': r['url'], 'source': 'references'})
            continue
        m = COMMIT_URL.match(r['url'])
        if m:
            repo = re.sub(r'/pull/\d+$', '', norm_repo(m[1]))  # github .../pull/12/commits/<sha>
            out.setdefault(m[2], {'repo': repo, 'commit': m[2], 'url': re.split(r'%2C|[,;)\s]', r['url'])[0], 'source': 'references'})
    repo_of = {}
    for a in row['affected']:
        if a.get('repo'):
            repo_of[family(f"{norm(a.get('vendor'))}:{norm(a.get('product'))}")] = norm_repo(a['repo'])
    for p in row['products']:
        for c in p.get('fixed_commits') or ():
            out.setdefault(c, {'repo': repo_of.get(p['product_key']), 'commit': c, 'url': None, 'source': 'CNA git range'})
    for pk in row['packages']:
        for g in pk.get('git_fixes') or ():
            out.setdefault(g['commit'], {'repo': norm_repo(g['repo']), 'commit': g['commit'], 'url': None, 'source': pk['source']})
    # Short and full SHAs of one commit: keep the full one.
    for key in list(out):
        sha = re.match(r'[0-9a-f]{7,40}(?![0-9a-z])', key)
        c = out.pop(key)
        if sha:
            c['commit'] = sha[0]
            out.setdefault(sha[0], c)
    for c in out.values():
        if not c['url'] and c['repo'] and re.match(r'https://(github\.com|gitlab\.com)/', c['repo']):
            c['url'] = c['repo'] + ('/commit/' if 'github.com' in c['repo'] else '/-/commit/') + c['commit']
    full = [c for c in out if len(c) == 40]
    return [out[c] for c in sorted(out) if len(c) == 40 or not any(f.startswith(c) for f in full)][:COMMITS_MAX]


def repositories(row, commits):
    repos = {norm_repo(a['repo']) for a in row['affected'] if a.get('repo')}
    repos |= {c['repo'] for c in commits if c['repo']}
    return sorted(r for r in repos if r.startswith('http'))


COMMITS_MAX = 50


def summary_line(row):
    """**derived** one-sentence digest of the row's own fields, for search results and assistants. No new facts."""
    if row['state'] != 'PUBLISHED':
        return None
    what = ' and '.join(row['vuln_class'][:2]) or 'Vulnerability'
    names = [p['product_key'].split(':', 1) for p in sorted(
        row['products'], key=lambda p: (-len(p['sources']), p['product_key']))[:2]]
    def short(t):
        if len(t) <= 50:
            return t
        t = t[:49]
        return (t[:t.rindex('(')] if t.count('(') > t.count(')') else t).rstrip(' ,;.') + '…'

    where = ', '.join(f'{short(prod)} ({short(ven)})' if ven else short(prod) for ven, prod in names)
    more = len(row['products']) - len(names)
    parts = [what[0].upper() + what[1:] + (f' in {where}' if where else '') + (f' and {more} other products' if more > 0 else '')]
    if (row['exposure'] or {}).get('remote_unauthenticated'):
        parts[0] += ', reachable over the network without authentication'
    sev = row['severity']
    if sev:
        label = 'No impact scored' if sev['band'] == 'none' else sev['band'].capitalize()
        parts.append(f"{label} (CVSS {sev['score']}, {sev['source']})")
    s = row['exploit_summary']
    if s.get('kev') or s.get('euvd_exploited') or (row['ssvc'] or {}).get('exploitation') == 'active':
        parts.append('Known to be exploited (' + ', '.join(x for x, on in (('CISA KEV', s.get('kev')),
            ('ENISA', s.get('euvd_exploited')), ('CISA SSVC', (row['ssvc'] or {}).get('exploitation') == 'active')) if on) + ')')
    elif s.get('public_exploit'):
        parts.append('Public exploit code referenced')
    rem = row['remediation']
    parts.append('Fixed versions or patches documented' if rem.get('has_documented_fix') else 'No fix documented in the sources')
    return '. '.join(parts) + '.'


VERSION_RANK = {'4.0': 4, '3.1': 3, '3.0': 2, '3.x': 2, '2.0': 1}
AV = {'N': 'network', 'A': 'adjacent', 'L': 'local', 'P': 'physical'}
LEVEL = {'N': 'none', 'L': 'low', 'H': 'high', 'M': 'medium'}
AU = {'N': 'none', 'S': 'low', 'M': 'high'}  # CVSS v2 Authentication -> privileges required
UI = {'N': 'none', 'R': 'required', 'P': 'required', 'A': 'required'}


def primary_cvss(row):
    """One score to sort and filter by: the CNA's own score first, then CISA ADP, then NVD, then any other source;
    within a source the newest CVSS version. All scores stay listed in `cvss`."""
    def rank(c):
        src = c['source']
        who = 0 if src == row['assigner'] else 1 if src == 'CISA-ADP' else 2 if src == 'NVD' else 3
        return (who, -VERSION_RANK.get(c.get('version'), 0))
    scored = [c for c in row['cvss'] if isinstance(c.get('score'), (int, float))]
    if any(c['score'] > 0 for c in scored):
        # A zero beside real scores is a placeholder (GitHub CNA 'C:N/I:N/A:N'); it stays listed, never primary.
        scored = [c for c in scored if c['score'] > 0]
    return min(scored, key=rank) if scored else None


def parse_vector(vector):
    """CVSS v2/v3/v4 vector -> exposure facts (attack vector, privileges, user interaction, complexity)."""
    parts = dict(x.split(':', 1) for x in (vector or '').strip('()').split('/') if ':' in x and not x.startswith('CVSS'))
    if 'AV' not in parts:
        return None
    pr = LEVEL.get(parts['PR']) if 'PR' in parts else AU.get(parts.get('Au'))
    av = AV.get(parts['AV'])
    return {'attack_vector': av, 'attack_complexity': LEVEL.get(parts.get('AC')), 'privileges_required': pr,
            'user_interaction': UI.get(parts.get('UI')) if 'UI' in parts else None,
            'remote_unauthenticated': av == 'network' and pr == 'none'}


# Our own grouping of CWE IDs into plain classes; a CWE not listed inherits its nearest listed parent (CWE-1000 view).
CWE_CLASS = {}
for _cls, _ids in {
    'memory corruption': (119, 120, 121, 122, 123, 124, 787, 416, 415, 843, 190, 191, 680, 131, 134, 762, 763, 822,
                          823, 824, 825, 590, 1284, 170),
    'out-of-bounds read': (125, 126, 127), 'null pointer dereference': (476,),
    'cross-site scripting': (79, 80, 83, 87), 'SQL injection': (89, 564), 'OS command injection': (78, 77),
    'code injection': (94, 95, 96, 1336, 917), 'other injection': (74, 75, 88, 90, 91, 93, 113, 116, 117, 643, 652, 1236, 707, 150, 913),
    'path traversal': (22, 23, 24, 35, 36, 73), 'link following': (59, 61), 'deserialization': (502,),
    'server-side request forgery': (918,), 'XML external entity': (611, 776), 'cross-site request forgery': (352,),
    'open redirect': (601,), 'unrestricted file upload': (434,),
    'authentication bypass': (287, 288, 290, 294, 304, 306, 307, 1390, 640),
    'missing or incorrect authorization': (862, 863, 284, 285, 639, 425, 732, 276, 281),
    'privilege management': (269, 250, 266, 267, 268, 270, 274),
    'hardcoded or weak credentials': (798, 259, 321, 521, 522, 256, 257, 260, 255),
    'information disclosure': (200, 201, 203, 209, 212, 215, 359, 532, 538, 548, 552, 497),
    'cryptographic weakness': (310, 326, 327, 328, 330, 338, 295, 297, 347, 345, 757, 916, 759, 760),
    'denial of service': (400, 770, 772, 401, 404, 674, 835, 834, 1333, 407, 789, 409, 399),
    'race condition': (362, 364, 366, 367), 'improper input validation': (20, 1285, 1287, 129),
    'misconfiguration': (16, 1188, 15), 'business logic': (840, 841),
    'access control': (264, 668, 280, 602, 693, 254), 'file inclusion': (98, 829),
    'untrusted search path': (426, 427, 428), 'numeric error': (189, 369, 682, 193, 681, 704),
    'uninitialized resource': (908, 457, 665, 909), 'reachable assertion': (617,),
    'cleartext or missing encryption': (319, 311, 312, 922, 313, 315), 'improper synchronization': (667, 833, 662, 820, 821),
    'session management': (613, 384, 614, 1004), 'exception handling': (754, 755, 248, 252, 703),
    'prototype pollution': (1321,), 'UI misrepresentation and clickjacking': (451, 1021),
    'HTTP request smuggling': (444,), 'embedded malicious code': (506, 912), 'mass assignment': (915,),
    'interpretation conflict': (436, 437), 'unintended proxy': (441,), 'incomplete denylist': (184,),
    'logic error': (670, 697, 696, 440, 1025), 'externally controlled reference': (610, 470, 706, 669),
    'resource lifetime': (672, 664, 666), 'active debug code': (489,), 'permission issues': (275,),
    'insecure temporary file': (377, 378, 379), 'vulnerable third-party component': (1395, 1104, 937, 1035),
    'missing rate limiting': (799,), 'insufficient logging': (778, 223), 'data processing errors': (19, 178),
}.items():
    for _i in _ids:
        CWE_CLASS[f'CWE-{_i}'] = _cls


def cwe_class(cwe, cwes, depth=0):
    if cwe in CWE_CLASS:
        return CWE_CLASS[cwe]
    if depth > 12:
        return None
    for parent in (cwes.get(cwe) or {}).get('parents', ()):
        found = cwe_class(parent, cwes, depth + 1)
        if found:
            return found
    return None


def priority(row):
    """Our triage hint from the row's own signals, never a substitute for the vendor's advice.
    act now: listed as exploited (CISA KEV, ENISA, or CISA SSVC 'active'); high: public exploit or PoC, exploitation
    reports, EPSS >= 0.1, or critical and reachable remotely without authentication; medium: score >= 7, or >= 4 and
    remote without authentication; low: other scored rows; unknown: no score and no signal."""
    if row['state'] != 'PUBLISHED':
        return None
    s, sev, exp = row['exploit_summary'], row['severity'] or {}, row['exposure'] or {}
    ssvc = (row['ssvc'] or {}).get('exploitation')
    score = sev.get('score')
    reasons = [r for r, on in (
        ('CISA KEV', s.get('kev')), ('ENISA exploited', s.get('euvd_exploited')), ('SSVC exploitation active', ssvc == 'active'),
        ('public exploit', s.get('public_exploit')), ('SSVC proof of concept', ssvc == 'poc'),
        ('exploitation sightings', s.get('sightings_exploited')),
        ('EPSS >= 0.1', (row['epss'] or {}).get('score', 0) >= 0.1),
        ('remote without authentication', exp.get('remote_unauthenticated')),
        (f'CVSS {score}', score is not None)) if on]
    if s.get('kev') or s.get('euvd_exploited') or ssvc == 'active':
        level = 'act now'
    elif (s.get('public_exploit') or ssvc == 'poc' or s.get('sightings_exploited')
          or (row['epss'] or {}).get('score', 0) >= 0.1 or (score is not None and score >= 9 and exp.get('remote_unauthenticated'))):
        level = 'high'
    elif score is not None and (score >= 7 or (score >= 4 and exp.get('remote_unauthenticated'))):
        level = 'medium'
    elif score is not None:
        level = 'low'
    else:
        level = 'unknown'
    return {'level': level, 'reasons': reasons, 'method': 'AI Science Tracker heuristic v1'}


def id_num(i):
    m = re.search(r'(\d+)$', i)
    return (i.rsplit('-', 1)[0], int(m[1]) if m else 0, i)


EXPLOIT_SOURCES = ('exploitdb', 'metasploit', 'nuclei', 'poc_github')


COUNT_FIELDS = ('total', 'kev', 'exploited', 'ransomware', 'public_exploit', 'remote_unauthenticated',
                'with_documented_fix')
COUNTER_FIELDS = ('by_year', 'by_severity', 'serious_by_year', 'by_priority', 'by_maturity', 'vuln_class', 'cwe',
                  'top_products', 'variants')
TOP_N = {'vuln_class': 30, 'cwe': 15, 'top_products': 15, 'variants': 20}


def tally_new(**fields):
    return {**fields, **{f: 0 for f in COUNT_FIELDS}, **{f: collections.Counter() for f in COUNTER_FIELDS},
            'latest_published': None, 'max_epss': None}


def tally_add(t, row, products=()):
    year = (row['published'] or '')[:4] or 'unknown'
    score = max_score(row)  # counts use the highest attributed score, as the product comparison always has
    t['total'] += 1
    t['kev'] += row['kev'] is not None
    t['exploited'] += (row['priority'] or {}).get('level') == 'act now'
    t['public_exploit'] += bool(row['exploit_summary'].get('public_exploit'))
    t['ransomware'] += bool(row['exploit_summary'].get('ransomware'))
    t['by_maturity'][row['exploit_summary'].get('maturity') or 'none known'] += 1
    t['remote_unauthenticated'] += bool((row['exposure'] or {}).get('remote_unauthenticated'))
    t['with_documented_fix'] += bool(row['remediation'].get('has_documented_fix'))
    t['by_year'][year] += 1
    t['by_severity'][band(score)] += 1
    if score is not None and score >= 7:
        t['serious_by_year'][year] += 1
    t['by_priority'][(row['priority'] or {}).get('level') or 'none'] += 1
    t['vuln_class'].update(row['vuln_class'])
    t['cwe'].update(c['id'] for c in row['cwe'])
    t['top_products'].update(products)
    if row['published'] and (t['latest_published'] or '') < row['published'][:10]:
        t['latest_published'] = row['published'][:10]
    epss = (row['epss'] or {}).get('score')
    if epss is not None and (t['max_epss'] is None or epss > t['max_epss']):
        t['max_epss'] = epss




def tally_finish(t):
    """Counters -> sorted dicts (set order changes between runs); long ones keep their top entries."""
    for f in COUNTER_FIELDS:
        items = sorted(t[f].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N[f]] if f in TOP_N else sorted(t[f].items())
        t[f] = dict(items)
    t['variants'] = list(t['variants'])
    if not t['top_products']:
        del t['top_products']
    return t


class Products:
    """Per product family, per vendor and per CWE counts of published vulnerabilities."""

    def __init__(self):
        self.data, self.vendors, self.weaknesses = {}, {}, {}

    def add(self, row, cwes=None):
        if row['state'] != 'PUBLISHED':
            return
        # The row's own product families, so the aggregates count exactly what the rows list.
        keys = {p['product_key']: set(p['names']) for p in row['products']}
        packages = {p['product_key'] for p in row['products'] if p['ecosystems'] and p['types'] == ['package']}
        for key, variants in keys.items():
            vendor, product = key.split(':', 1)
            p = self.data.setdefault(key, tally_new(product_key=key, vendor=vendor, product=product,
                                                    category=category_of(key),
                                                    lifecycle=(LIFECYCLE.get(key) or {}).get('id')))
            p['variants'].update(variants)
            tally_add(p, row)
        for vendor in sorted({k.split(':', 1)[0] for k in keys if k not in packages} - {''}):  # an ecosystem is no vendor
            v = self.vendors.setdefault(vendor, tally_new(vendor=vendor))
            tally_add(v, row, [k for k in keys if k.startswith(vendor + ':')])
        for c in row['cwe']:
            w = self.weaknesses.setdefault(c['id'], tally_new(cwe_id=c['id'], name=c['name']))
            tally_add(w, row, list(keys))

    def rows(self):
        return sorted((tally_finish(p) for p in self.data.values()), key=lambda p: (-p['total'], p['product_key']))

    def vendor_rows(self):
        return sorted((tally_finish(v) for v in self.vendors.values()), key=lambda v: (-v['total'], v['vendor']))

    def weakness_rows(self, cwes):
        out = []
        for w in self.weaknesses.values():
            w = tally_finish(w)
            w['class'] = cwe_class(w['cwe_id'], cwes)
            del w['cwe']  # a weakness's related CWEs are in the CWE catalog
            out.append(w)
        return sorted(out, key=lambda w: (-w['total'], w['cwe_id']))


def load_kev(path):
    data = json.loads(path.read_text())
    return {v['cveID']: {'date_added': v.get('dateAdded'), 'due_date': v.get('dueDate'),
                         'ransomware': v.get('knownRansomwareCampaignUse'), 'name': v.get('vulnerabilityName'),
                         'required_action': v.get('requiredAction'), 'description': v.get('shortDescription'),
                         'notes': v.get('notes')}
            for v in data['vulnerabilities']}


def load_epss(path):
    with gzip.open(path, 'rt') as f:
        header = f.readline()
        date = (re.search(r'score_date:(\S+)', header) or [None, None])[1]
        return {r['cve']: {'score': float(r['epss']), 'percentile': float(r['percentile']), 'date': date[:10] if date else None}
                for r in csv.DictReader(f)}


def euvd_date(s):
    """ENISA writes 'Dec 10, 2021, 12:00:00 AM'; keep the ISO day, or the raw text if it ever changes format."""
    import datetime
    try:
        return datetime.datetime.strptime(s, '%b %d, %Y, %I:%M:%S %p').date().isoformat() if s else None
    except ValueError:
        return s


def load_euvd(path):
    out = {}
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            for a in (r.get('aliases') or '').split():
                if CVE_RE.match(a):
                    out[a] = {'id': r['id'], 'exploited_since': euvd_date(r.get('exploitedSince')),
                              'url': f"https://euvd.enisa.europa.eu/vulnerability/{r['id']}"}
    return out


def load_nvd(folder):
    out = {}
    for path in sorted(folder.glob('nvdcve-2.0-[0-9]*.json.gz')):
        with gzip.open(path, 'rt') as f:
            for item in json.load(f)['vulnerabilities']:
                v = item['cve']
                cvss = []
                for key, metrics in (v.get('metrics') or {}).items():
                    for m in metrics:
                        if m.get('source') == 'nvd@nist.gov' and 'cvssData' in m:
                            c = m['cvssData']
                            cvss.append({'source': 'NVD', 'version': c.get('version'), 'score': c.get('baseScore'),
                                         'vector': c.get('vectorString')})
                cpe = [{k: m[k] for k in ('criteria', 'versionStartIncluding', 'versionStartExcluding',
                                          'versionEndIncluding', 'versionEndExcluding') if k in m}
                       for conf in v.get('configurations') or [] for node in conf.get('nodes') or []
                       for m in node.get('cpeMatch') or [] if m.get('vulnerable')]
                cwe = sorted({d['value'] for w in v.get('weaknesses') or [] for d in w.get('description') or []
                              if CWE_RE.match(d.get('value') or '')})
                refs = [{'url': r['url'], 'tags': r.get('tags') or []} for r in v.get('references') or [] if r.get('url')]
                out[v['id']] = {'cvss': cvss, 'cpe': cpe, 'status': v.get('vulnStatus'), 'cwe': cwe, 'references': refs}
    return out


def load_cwe(path):
    """MITRE CWE catalog zip -> {'CWE-79': {'name': ..., 'capec': ['CAPEC-63', ...]}} for weaknesses, categories, views."""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    ns = root.tag.split('}')[0] + '}'
    out = {}
    for tag in ('Weakness', 'Category', 'View', 'Grouping'):  # CWE 5 calls the old NVD categories 'Grouping'
        for el in root.iter(ns + tag):
            capec = {f"CAPEC-{r.get('CAPEC_ID')}" for r in el.iter(ns + 'Related_Attack_Pattern')}
            parents = sorted({f"CWE-{r.get('CWE_ID')}" for r in el.iter(ns + 'Related_Weakness')
                              if r.get('Nature') == 'ChildOf' and r.get('View_ID') == '1000'}, key=id_num)
            out[f"CWE-{el.get('ID')}"] = {'name': el.get('Name'), 'capec': sorted(capec, key=id_num), 'parents': parents,
                                          'top25': False, 'owasp': []}
    for el in root.iter():  # list memberships: the Top 25 view and the OWASP Top Ten category groupings
        tag = el.tag.split('}')[1]
        m = OWASP_RE.match(el.get('Name') or '') if tag in ('Category', 'Grouping') else None
        if not (m or (tag == 'View' and el.get('ID') == TOP25_VIEW)):
            continue
        for member in el.iter(ns + 'Has_Member'):
            slot = out.get(f"CWE-{member.get('CWE_ID')}")
            if slot is None:
                continue
            if m:
                slot['owasp'] = sorted(set(slot['owasp']) | {f'{m[2]}:{m[1]} {m[3]}'})
            else:
                slot['top25'] = True
    return out


def load_capec(path):
    """-> ({'CAPEC-1': name}, {'CAPEC-1': [{'id': 'T1574.010', 'name': ...}]}) from the MITRE CAPEC catalog."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    ns = root.tag.split('}')[0] + '}'
    names, attack = {}, {}
    for el in root.iter(ns + 'Attack_Pattern'):
        cid = f"CAPEC-{el.get('ID')}"
        names[cid] = el.get('Name')
        attack[cid] = [{'id': 'T' + m.findtext(ns + 'Entry_ID').strip(), 'name': m.findtext(ns + 'Entry_Name')}
                       for m in el.iter(ns + 'Taxonomy_Mapping')
                       if m.get('Taxonomy_Name') == 'ATTACK' and (m.findtext(ns + 'Entry_ID') or '').strip()]
    return names, attack


def load_exploits(src):
    """Public exploit references by CVE: Exploit-DB, Metasploit modules, Nuclei templates, PoC-in-GitHub.

    Only IDs, links, dates and small facts are kept (Exploit-DB is GPL-2.0, so no titles or code).
    PoC-in-GitHub repositories are unverified and may be fake or malicious; they are counted and the most starred kept.
    """
    out = collections.defaultdict(lambda: {'items': [], 'counts': collections.Counter()})
    stats = collections.Counter()

    def add(cves, kind, item):
        cves = sorted({c for c in cves if CVE_RE.match(c)})
        stats[kind] += 1
        stats[kind + '_with_cve'] += bool(cves)
        for c in cves:
            out[c]['items'].append(item)
            out[c]['counts'][kind] += 1

    edb = src / 'exploitdb/files_exploits.csv'
    if edb.exists():
        with open(edb, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                add((r.get('codes') or '').split(';'), 'exploitdb',
                    {'source': 'Exploit-DB', 'id': f"EDB-{r['id']}", 'url': f"https://www.exploit-db.com/exploits/{r['id']}",
                     'date': r.get('date_published') or None, 'type': r.get('type') or None,
                     'platform': r.get('platform') or None, 'verified': r.get('verified') == '1'})
    msf = src / 'metasploit/modules_metadata_base.json'
    if msf.exists():
        for m in sorted(json.loads(msf.read_text()).values(), key=lambda m: m['fullname']):
            add(m.get('references') or [], 'metasploit',
                {'source': 'Metasploit', 'id': m['fullname'], 'url': f"https://www.rapid7.com/db/modules/{m['fullname']}/",
                 'date': m.get('disclosure_date'), 'type': m.get('type'), 'check': bool(m.get('check'))})
    nuclei = src / 'nuclei/repo/cves.json'
    if nuclei.exists():
        with open(nuclei) as f:
            for line in f:
                if line.strip():
                    t = json.loads(line)
                    add([t.get('ID') or ''], 'nuclei',
                        {'source': 'Nuclei', 'id': t['file_path'],
                         'url': f"https://github.com/projectdiscovery/nuclei-templates/blob/main/{t['file_path']}",
                         'severity': (t.get('Info') or {}).get('Severity')})
    for path in sorted((src / 'pocgithub/repo').glob('*/CVE-*.json')):
        repos = sorted((r for r in json.loads(path.read_text()) if not r.get('fork')),
                       key=lambda r: (-(r.get('stargazers_count') or 0), r.get('full_name') or ''))
        cve = path.stem
        for r in repos[:POC_KEEP]:
            add([cve], 'poc_github', {'source': 'PoC-in-GitHub (unverified)', 'id': r['full_name'], 'url': r['html_url'],
                                      'date': (r.get('created_at') or '')[:10] or None,
                                      'stars': r.get('stargazers_count') or 0})
        if CVE_RE.match(cve) and len(repos) > POC_KEEP:
            out[cve]['counts']['poc_github'] += len(repos) - POC_KEEP
            stats['poc_github_not_listed'] += len(repos) - POC_KEEP
    return dict(out), dict(stats)


# National and other vulnerability databases from CIRCL Vulnerability-Lookup dumps (work/vuln-global/circl).
# Content is reused only where docs/vulnerability-sources.md found open terms; elsewhere ID, link and dates only.
NATIONAL_DBS = {  # dump -> (source name, own-ID prefix order for the group's main ID)
    'jvndb': 'JVN iPedia', 'variot': 'VARIoT', 'cnvd': 'CNVD', 'fstec': 'FSTEC BDU'}
NATIONAL_ORDER = ('JVNDB', 'VAR', 'CNVD', 'BDU')
REFERENCE_ONLY = 'reference only (no reuse terms found)'
OTHER_ID_RE = re.compile(r'\b(CVE-\d{4}-\d{4,}|CNVD-\d{4}-\d+|JVNDB-\d{4}-\d+|BDU:\d{4}-\d+|VAR-\d+-\d+)\b')


def circl_url(r):
    return 'https://vulnerability.circl.lu/vuln/' + str(r.get('vulnerability-lookup:id') or '')


def ddmmyyyy(s):
    m = re.match(r'(\d\d)\.(\d\d)\.(\d{4})', s or '')
    return f'{m[3]}-{m[2]}-{m[1]}' if m else None


def national_record(dump, r):
    """-> (own id, url, published date, set of linked IDs) for one national-database record."""
    if dump == 'jvndb':
        refs = r.get('sec:references') or []
        refs = refs if isinstance(refs, list) else [refs]
        return (r['sec:identifier'], r.get('link') or circl_url(r), (r.get('dcterms:issued') or '')[:10] or None,
                {x.get('@id') for x in refs if isinstance(x, dict) and x.get('@id')})
    if dump == 'cnvd':
        cv = (r.get('cves') or {}).get('cve') or []
        cv = cv if isinstance(cv, list) else [cv]
        return (r['number'], f"https://www.cnvd.org.cn/flaw/show/{r['number']}", r.get('openTime') or r.get('submitTime'),
                {c.get('cveNumber', '').strip() for c in cv})
    if dump == 'fstec':
        bdu = r['Идентификатор']
        return (bdu, f"https://bdu.fstec.ru/vul/{bdu.split(':', 1)[1]}", ddmmyyyy(r.get('Дата публикации')),
                set(OTHER_ID_RE.findall(r.get('Идентификаторы других систем описаний уязвимости') or '')))
    if dump == 'variot':
        ids = {d.get('id') for d in (r.get('external_ids') or {}).get('data') or []}
        dates = [d['date'] for d in (r.get('sources_release_date') or {}).get('data') or [] if (d.get('date') or '') >= '1980']  # 1900-01-01 = unknown
        return (r['id'], f"https://www.variotdbs.pl/vuln/{r['id']}/", min(dates)[:10] if dates else None,
                {i for i in ids if i and OTHER_ID_RE.fullmatch(i)})
    raise ValueError(dump)


def iter_ndjson(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def norm_vuln_id(i):
    i = (i or '').strip()
    u = i.upper()
    if u.startswith('GHSA-'):
        return 'GHSA-' + i[5:].lower()
    return u


def load_other_dbs(folder):
    """Cross-references, extra non-CVE entries, GCVE aliases and sightings from the CIRCL dumps.

    Returns {'refs': {cve: {id: ref}}, 'aliases': {cve: {gcve}}, 'rows': [row], 'sightings': {id: summary}, 'stats': {}}.
    """
    out = {'refs': collections.defaultdict(dict), 'aliases': collections.defaultdict(set), 'rows': [],
           'sightings': {}, 'stats': collections.Counter()}
    if not folder.exists():
        return out
    stats = out['stats']

    def ref(cve, rid, source, license, url):
        out['refs'][cve][rid] = {'id': rid, 'source': source, 'license': license, 'url': url}

    # 1. National databases. A record citing a CVE, or citing/cited by a record that does (one hop), is a reference
    # of those CVEs only; records with no CVE are grouped when they cite each other and become extra rows.
    recs = {}
    for dump, name in NATIONAL_DBS.items():
        path = folder / f'{dump}.ndjson'
        if not path.exists():
            continue
        for r in iter_ndjson(path):
            if r.get('isEvent') == '事件型漏洞':  # CNVD "event" entries concern one website, not a product
                stats['cnvd_site_events_skipped'] += 1
                continue
            rid, url, date, linked = national_record(dump, r)
            stats[f'{dump}_records'] += 1
            recs[rid] = {'id': rid, 'source': name, 'url': url, 'date': date, 'linked': linked - {rid, ''}}
    cited_by = collections.defaultdict(set)
    for rid, x in recs.items():
        for other in x['linked']:
            cited_by[other].add(rid)

    def direct(rid):
        return {i for i in recs[rid]['linked'] if CVE_RE.match(i)} if rid in recs else set()

    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for rid, x in recs.items():
        neighbours = {i for i in x['linked'] if i in recs} | cited_by[rid]
        cves = direct(rid) | {c for n in neighbours for c in direct(n)}
        if cves:
            for c in cves:
                ref(c, rid, x['source'], REFERENCE_ONLY, x['url'])
            stats['national_linked_to_cve'] += 1
            continue
        find(rid)
        for n in neighbours:
            parent[find(n)] = find(rid)
    groups = collections.defaultdict(list)
    for node in list(parent):
        if node in recs:
            groups[find(node)].append(recs[node])
    for own in groups.values():
        own.sort(key=lambda x: (NATIONAL_ORDER.index(next(p for p in NATIONAL_ORDER if x['id'].startswith(p))), x['id']))
        main = own[0]
        stats['national_rows'] += 1
        out['rows'].append({**BLANK, 'id': main['id'], 'state': 'PUBLISHED', 'aliases': sorted(x['id'] for x in own[1:]),
                            'published': min(filter(None, (x['date'] for x in own)), default=None),
                            'advisories': [{'id': x['id'], 'source': x['source'], 'license': REFERENCE_ONLY,
                                            'url': x['url']} for x in own],
                            'references': [{'url': x['url'], 'tags': [], 'sources': [x['source']]} for x in own],
                            'sources': sorted({f"{x['source']} ({REFERENCE_ONLY})" for x in own})})

    # 2. Advisories that list CVEs: CERT-FR (Licence Ouverte 2.0) and vendor/CERT CSAF feeds (no reuse terms found).
    for path in sorted(folder.glob('certfr_*.ndjson')):
        kind = path.stem.split('_', 1)[1]
        for r in iter_ndjson(path):
            rid = r.get('reference')
            cves = sorted({c.get('name') for c in r.get('cves') or [] if CVE_RE.match(c.get('name') or '')})
            stats['certfr_records'] += 1
            for c in cves:
                ref(c, rid, 'CERT-FR', 'Licence-Ouverte-2.0', f'https://www.cert.ssi.gouv.fr/{kind}/{rid}/')
    for path in sorted(folder.glob('csaf_*.ndjson')):
        for r in iter_ndjson(path):
            doc = r.get('document') or {}
            rid = (doc.get('tracking') or {}).get('id')
            url = next((x.get('url') for x in doc.get('references') or [] if x.get('category') == 'self'), None)
            publisher = (doc.get('publisher') or {}).get('name') or path.stem[5:]
            stats['csaf_records'] += 1
            for v in r.get('vulnerabilities') or []:
                if CVE_RE.match(v.get('cve') or ''):
                    ref(v['cve'], rid, f'{publisher} (CSAF)', REFERENCE_ONLY, url or circl_url(r))

    # 3. GCVE: GNA-1 is CIRCL's own (CC BY 4.0); other numbering authorities are kept as reference only.
    for path in sorted(folder.glob('gna-*.ndjson')) + sorted(folder.glob('moksha.ndjson')):
        open_content = path.stem == 'gna-1'
        for r in iter_ndjson(path):
            meta = r.get('cveMetadata') or {}
            cid = meta.get('cveId') or ''
            cid = cid.upper() if CVE_RE.match(cid.upper()) else cid
            gid = meta.get('vulnId') or next((a for a in meta.get('alternateIds') or [] if a.upper().startswith('GCVE-')),
                                             None) or cid
            gid = gid.upper() if gid.upper().startswith('GCVE-') else gid
            if not gid:
                stats['gcve_without_id'] += 1
                continue
            stats['gcve_records'] += 1
            if CVE_RE.match(cid):
                if gid != cid:
                    out['aliases'][cid].add(gid)
                continue
            cna = (r.get('containers') or {}).get('cna') or {}
            url = 'https://vulnerability.circl.lu/vuln/' + gid.lower()
            label = 'GCVE ' + gid.split('-')[1] if gid.startswith('GCVE-') else path.stem
            row = {**BLANK, 'id': gid, 'state': meta.get('state') or 'PUBLISHED',
                   'aliases': sorted({cid} - {gid, ''}), 'published': meta.get('datePublished'),
                   'updated': meta.get('dateUpdated'),
                   'advisories': [{'id': gid, 'source': label, 'license': 'CC-BY-4.0' if open_content else REFERENCE_ONLY,
                                   'url': url}],
                   'sources': [f"{label} ({'CIRCL, CC-BY-4.0' if open_content else REFERENCE_ONLY})"]}
            if open_content:
                desc = next((d['value'] for d in cna.get('descriptions') or [] if d.get('lang', '').startswith('en')), '')
                row.update(title=cna.get('title'), description=desc[:DESC_MAX], affected=cna_affected(cna, label),
                           cvss=cvss_from_metrics(cna.get('metrics'), label), cwe=sorted(problem_cwes(cna)))
                refs = collections.OrderedDict()
                add_refs(refs, cna.get('references'), label)
                row['references'] = list(refs.values())
            else:
                row['references'] = [{'url': url, 'tags': [], 'sources': [label]}]
            stats['gcve_rows'] += 1
            out['rows'].append(row)

    # 4. Sightings (no reuse terms found): only counts by type and first/last date, never the posts.
    path = folder / 'sightings.ndjson'
    if path.exists():
        acc = {}
        for r in iter_ndjson(path):
            vid = norm_vuln_id(r.get('vulnerability'))
            t = r.get('type') or 'seen'
            ts = (r.get('creation_timestamp') or '')[:10]
            a = acc.setdefault(vid, {'counts': collections.Counter(), 'first': ts, 'last': ts})
            a['counts'][t] += 1
            if ts:
                a['first'] = min(a['first'] or ts, ts)
                a['last'] = max(a['last'], ts)
            stats['sightings'] += 1
        out['sightings'] = {k: {'counts': dict(sorted(v['counts'].items())), 'first': v['first'] or None,
                                'last': v['last'] or None, 'source': 'CIRCL Vulnerability-Lookup sightings'}
                            for k, v in acc.items()}
    out['stats'] = dict(stats)
    return out


def load_ghsa_unreviewed(folder):
    """GitHub's unreviewed advisories (CC BY 4.0) are copies of CVEs that OSV does not export: keep their GHSA IDs as
    aliases of those CVEs. -> {cve: {ghsa}}"""
    out = collections.defaultdict(set)
    for path in sorted(folder.glob('**/GHSA-*.json')):
        r = json.loads(path.read_text())
        if r.get('withdrawn'):
            continue
        for a in r.get('aliases') or []:
            if CVE_RE.match(a):
                out[a].add(r['id'])
    return out


PURL_ECOSYSTEM = {'pypi': 'pypi', 'npm': 'npm', 'maven': 'maven', 'golang': 'go', 'cargo': 'crates.io', 'gem': 'rubygems',
                  'nuget': 'nuget', 'composer': 'packagist', 'hex': 'hex', 'pub': 'pub', 'hackage': 'hackage'}


def load_eol(path):
    """endoflife.date (MIT) -> {product_key: lifecycle}, matched through the CPE and purl identifiers it publishes."""
    from urllib.parse import unquote
    if not path.exists():
        return {}
    out = {}
    for prod in json.loads(path.read_text())['result']:
        keys = set()
        for ident in prod.get('identifiers') or []:
            i = ident.get('id') or ''
            if ident.get('type') == 'cpe':
                parts = i.replace('cpe:/', 'cpe:2.3:', 1).split(':')
                if len(parts) > 4:
                    keys.add(family(f"{norm(parts[3].replace('_', ' '))}:{norm(parts[4].replace('_', ' '))}"))
            elif ident.get('type') == 'purl':
                m = re.match(r'^pkg:([^/]+)/(.+?)(?:@.*)?$', i)
                if m and m[1] in PURL_ECOSYSTEM:
                    name = unquote(m[2])
                    name = name.replace('/', ':') if m[1] == 'maven' else name
                    keys.add(family(f'{PURL_ECOSYSTEM[m[1]]}:{norm(name)}'))
        life = {'id': prod['name'], 'label': prod.get('label'), 'url': (prod.get('links') or {}).get('html'),
                'releases': [{'name': r.get('name'), 'released': r.get('releaseDate'), 'eol_from': r.get('eolFrom'),
                              'is_eol': r.get('isEol'), 'maintained': r.get('isMaintained'), 'lts': r.get('isLts'),
                              'latest': (r.get('latest') or {}).get('name')} for r in prod.get('releases') or []]}
        for k in sorted(keys):
            out.setdefault(k, life)  # first product wins when two claim one key
    return out



def iter_osv(path):
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith('.json'):
                yield json.loads(z.read(name))


def iter_cvelist(path):
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if re.search(r'/CVE-\d{4}-\d+\.json$', name):
                yield json.loads(z.read(name))


def gz_text(path):
    """Gzip text writer with a fixed header time, so identical inputs give identical bytes."""
    return io.TextIOWrapper(gzip.GzipFile(path, 'wb', compresslevel=6, mtime=0), encoding='utf-8')


def write_jsonl(path, rows):
    n = 0
    with gz_text(path) as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            n += 1
    return n


def build(cve_records, osv_records, extra, out):
    """Stream rows to out/; extra has nvd, kev, epss, euvd. Returns the build report."""
    osv = OsvIndex()
    for rec in osv_records:
        osv.add(rec)
    osv.finalize()
    extra = dict(extra, osv=osv)
    products = Products()
    states = collections.Counter()
    seen = set()
    stats = collections.Counter()

    def count_links(row):
        index_row(row)
        stats['with_products'] += bool(row['products'])
        stats['with_cwe'] += bool(row['cwe'])
        stats['with_capec'] += bool(row['capec'])
        stats['with_public_exploit'] += row['exploit_summary']['public_exploit']
        stats['cwe_without_name'] += sum(1 for c in row['cwe'] if not c['name'])

    out.mkdir(parents=True, exist_ok=True)
    index = gz_text(out / 'product_versions.jsonl.gz')

    def index_row(row):
        """One line per (product, vulnerability) with its ranges: what a version check needs, without the full row."""
        if row['state'] != 'PUBLISHED':
            return
        for p in row['products']:
            if p['ranges'] or p['fixed']:
                index.write(json.dumps({'product_key': p['product_key'], 'id': row['id'], 'ranges': p['ranges'],
                                        'fixed': p['fixed'], 'cpe': p['cpe'], 'purl': p['purl'],
                                        'score': (row['severity'] or {}).get('score'),
                                        'priority': (row['priority'] or {}).get('level'), 'kev': row['kev'] is not None},
                                       ensure_ascii=False, separators=(',', ':')) + '\n')

    def rows():
        for rec in cve_records:
            row = cve_row(rec, extra)
            if row['id'] in seen:
                stats['duplicate_cve_files'] += 1
                continue
            seen.add(row['id'])
            states[row['state']] += 1
            for k in ('kev', 'euvd', 'epss'):
                stats[f'with_{k}'] += row[k] is not None
            stats['scored'] += max_score(row) is not None
            enrich(row, extra)
            count_links(row)
            products.add(row)
            yield row
        for cid in sorted(set(extra['kev']) - seen):
            # Reserved in the CVE List or published after the snapshot; keep them findable.
            seen.add(cid)
            stats['not_in_cve_list'] += 1
            yield enrich({**BLANK, 'id': cid, 'state': 'NOT_IN_CVE_LIST_SNAPSHOT',
                   'packages': list((osv.by_cve.get(cid) or {}).get('packages', [])),
                   'kev': extra['kev'].get(cid), 'euvd': extra['euvd'].get(cid), 'epss': extra['epss'].get(cid),
                   'sources': [s for s, d in (('CISA KEV (CC0-1.0)', extra['kev']), (EUVD_SOURCE, extra['euvd']),
                                              (EPSS_SOURCE, extra['epss'])) if cid in d]}, extra)
        other_rows = list(osv.non_cve_rows()) + list((extra.get('other') or {}).get('rows') or [])
        for row in other_rows:
            if row['id'] in seen:
                stats['extra_rows_duplicate_id'] += 1
                continue
            seen.add(row['id'])
            stats['non_cve_rows'] += 1
            stats['non_cve_rows_' + (row['sources'] or ['unknown'])[0].split(' (')[0]] += 1
            enrich(row, extra)
            count_links(row)
            products.add(row)
            yield row

    total = write_jsonl(out / 'vulnerabilities_global.jsonl.gz', rows())
    index.close()
    write_jsonl(out / 'malicious_packages.jsonl.gz', osv.malicious)
    product_rows = products.rows()
    with gz_text(out / 'products.json.gz') as f:
        json.dump(product_rows, f, separators=(',', ':'))
    categories = collections.defaultdict(list)  # curated categories only; uncategorised products stay out
    for p in product_rows:
        if p['category']:
            categories[p['category']].append({k: p[k] for k in (
                'product_key', 'total', 'kev', 'exploited', 'public_exploit', 'remote_unauthenticated',
                'with_documented_fix', 'by_severity', 'by_year', 'serious_by_year', 'latest_published')})
    with gz_text(out / 'product_lifecycle.json.gz') as f:
        json.dump(dict(sorted(LIFECYCLE.items())), f, separators=(',', ':'))
    with gz_text(out / 'vendors.json.gz') as f:
        json.dump(products.vendor_rows(), f, separators=(',', ':'))
    with gz_text(out / 'weaknesses.json.gz') as f:
        json.dump(products.weakness_rows(extra.get('cwe') or {}), f, separators=(',', ':'))
    with gz_text(out / 'categories.json.gz') as f:
        json.dump(dict(sorted(categories.items())), f, separators=(',', ':'))
    report = {
        'rows': total, 'cve_states': dict(states), **stats, 'malicious_packages': len(osv.malicious),
        'products': len(products.data), 'osv_records': dict(osv.counts), 'exploit_sources': extra.get('exploit_stats', {}),
        'other_sources': (extra.get('other') or {}).get('stats', {}),
        'cves_with_osv_content': sum(1 for c in osv.by_cve if c in seen),
        'osv_cves_missing_from_cvelist_count': sum(1 for c in osv.by_cve if c not in seen),
        'osv_cves_missing_from_cvelist': sorted(c for c in osv.by_cve if c not in seen)[:50],
        'kev_missing_from_cvelist': sorted(set(extra['kev']) - seen),
    }
    (out / 'build_report.json').write_text(json.dumps(report, indent=1))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--src', type=Path, default=ROOT / 'work/vuln-global')
    ap.add_argument('--out', type=Path, default=ROOT / 'work/vuln-global/build')
    a = ap.parse_args()
    extra = {'kev': load_kev(a.src / 'kev/known_exploited_vulnerabilities.json'),
             'epss': load_epss(next((a.src / 'epss').glob('*.csv.gz'))),
             'euvd': load_euvd(a.src / 'euvd/euvd_all.jsonl'), 'nvd': load_nvd(a.src / 'nvd'),
             'cwe': load_cwe(a.src / 'cwe/cwec_latest.xml.zip')}
    extra['capec'], extra['capec_attack'] = load_capec(a.src / 'capec/capec_latest.xml')
    extra['exploits'], extra['exploit_stats'] = load_exploits(a.src)
    LIFECYCLE.update(load_eol(a.src / 'eol/full.json'))
    extra['other'] = load_other_dbs(a.src / 'circl')
    for cve, ids in load_ghsa_unreviewed(a.src / 'ghsa/advisory-database/advisories/unreviewed').items():
        extra['other']['aliases'][cve] |= ids
    extra['sightings'] = extra['other']['sightings']
    report = build(iter_cvelist(a.src / 'cvelistv5/cves.zip'), iter_osv(a.src / 'osv/all.zip'), extra, a.out)
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, indent=1))


if __name__ == '__main__':
    main()
