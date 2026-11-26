#!/usr/bin/env python3
"""Generate the files that make discoveries shareable and the site indexable.

Outputs (all generated, never edit by hand; rerun this script instead):
  og/<id>.png      1200x630 social preview card, rendered with headless Chrome and
                   saved as a 32-color PNG with Pillow (`python3 -m pip install --user pillow`)
  share/<id>.html  full, indexable discovery page (self-canonical; no redirect, no noindex),
                   reusing the live header/footer from index.html and assets/catalog-ui.js
                   for the same source-check and correction text as the catalog (IMP-011)
  sitemap.xml, robots.txt  include every discovery page, so search engines can reach the
                   catalog's content, not only the 6 top-level pages

Usage:
  python3 scripts/generate_share.py            # pages, sitemap, robots, and changed cards
  python3 scripts/generate_share.py --force    # re-render every card
  python3 scripts/generate_share.py --no-images  # skip Chrome, retain existing entry images
  python3 scripts/generate_share.py --reuse-images  # refresh hashes after verifying unchanged card visuals

Cards use styles.css and the self-hosted font, so they follow docs/DESIGN.md automatically.
Discovery pages are generated, not hand-written, but still obey docs/DESIGN.md: same frame,
same stylesheet, same wording as the live catalog, extracted from index.html rather than
retyped, so they automatically track any nav or footer change made there.
"""
import argparse
import datetime
import html
import hashlib
import json
import os
import re
import unicodedata
import csv
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from model_families import discovery_links
from entities import organization as canonical_organization
from dataset_manifest import write_manifest, stamp_pages, write_component_jsonld
import evidence_levels

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://aisciencetracker.org/'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
SITE = 'AI Science Tracker'
DEFAULT_ALT = 'Preview card: AI Science Tracker, scientific discoveries enabled by AI, tracked from official announcements since 2020.'
NOT_ROOT_RELATIVE = re.compile(r'^(https?:|data:|mailto:|#|\.\./|/)')
DOSSIERS = {
    'materials': {
        '2023-11-gnome': 'gnome',
        '2023-11-a-lab': 'a-lab',
        '2025-01-mattergen': 'mattergen',
    },
    'mathematics': {
        '2023-12-funsearch': 'funsearch',
        '2025-11-alphaevolve-tao': 'alphaevolve',
        '2024-07-alphaproof-imo': 'alphaproof',
        '2026-09-openai-navier-stokes': 'navier-stokes',
    },
    'seismology': {
        '2025-09-ai-enhanced-seismic-catalog-exposes-a-ring-fault-system-at-campi-flegrei': 'campi-flegrei',
        '2025-04-regional-deep-learning-phase-picking-reveals-24-additional-earthquakes-in-a-gorda-ridge-swarm': 'gorda-ridge',
        '2024-08-machine-learning-identifies-regional-low-magnitude-seismic-unrest-before-the-ridgecrest-and-anchorage-earthquakes':
            'ridgecrest-anchorage',
    },
    'astronomy': {
        '2021-11-exominer': 'exominer',
        '2023-05-exominer-69': 'kepler-multiplicity',
        '2025-03-euclid-lenti': 'euclid',
    },
    'floods': {
        '2024-03-previsione-alluvioni': 'ungauged-basins',
        '2024-11-flood-hub-globale': 'seven-day-forecasts',
    },
}
DOSSIER_IDS = {entry_id: (topic, section) for topic, cases in DOSSIERS.items()
               for entry_id, section in cases.items()}


def esc(s):
    return html.escape(str(s), quote=True)


def lead_org(name):
    """Same rule as index.html: organizations listed together count under the first one named."""
    return canonical_organization(name)['label']


def score(d):
    r = d['relevance']
    # Same rule as CatalogUI.score: never more than one level above the evidence.
    return min(round((r['impact'] + r['validation'] + r['novelty']) / 3 * 20), (r['validation'] + 1) * 20)


def nice_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f'{d.day} {d:%b %Y}'


def clip(text, n):
    return text if len(text) <= n else text[:n - 1].rsplit(' ', 1)[0].rstrip(',;:') + '…'


SENTENCE_END = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9“"(])')


DESC_MIN = 110  # search snippets: shorter reads as thin, longer than hard is cut off


def describe(text, n=155, hard=160, lead=None):
    """Meta description made of whole sentences: as many as fit in n characters, or the first
    sentence alone when it fits in hard; only longer first sentences fall back to clip().
    A too-short result is prefixed with lead (usually the title) when given."""
    parts = SENTENCE_END.split(text.strip())
    out = ''
    for part in parts:
        candidate = f'{out} {part}'.strip()
        if len(candidate) > n:
            break
        out = candidate
    if not out and len(parts[0]) <= hard:
        out = parts[0]
    out = out or clip(text, n)
    if lead and len(out) < DESC_MIN:
        combined = f'{lead.rstrip(".")}. {text}'
        out = describe(combined, n, hard)
        return out if len(out) >= DESC_MIN else clip(combined, n)
    return out


def fit_title(page, limit=60):
    """Drop the site suffix, then clip, so search titles stay within limit characters."""
    def fix(m):
        title = html.unescape(m.group(1))
        if len(title) > limit:
            title = title.removesuffix(f' · {SITE}')
        return f'<title>{esc(clip(title, limit))}</title>'
    return re.sub(r'<title>(.*?)</title>', fix, page, count=1, flags=re.S)


def relocate(fragment):
    """Rewrite href/src values for a page one directory below the site root (share/id.html),
    so root-relative links copied verbatim out of a top-level page (index.html, "styles.css", ...)
    still resolve. Absolute, data:, mailto:, anchor and already-relocated links are left alone."""
    i18n_css = Path(__file__).resolve().parents[1] / 'assets' / 'i18n.css'
    if i18n_css.is_file():
        digest = hashlib.sha256(i18n_css.read_bytes()).hexdigest()[:12]
        fragment = fragment.replace('__I18N_CSS__', f'assets/i18n.css?v={digest}')
    def fix(m):
        attr, quote_char, value = m.group(1), m.group(2), m.group(3)
        if value == 'styles.css':
            value += '?v=' + hashlib.sha256((ROOT / 'styles.css').read_bytes()).hexdigest()[:12]
        if NOT_ROOT_RELATIVE.match(value):
            return m.group(0)
        return f'{attr}={quote_char}../{value}{quote_char}'
    return re.sub(r'(href|src)=(["\'])([^"\']+)\2', fix, fragment)


def site_frame():
    """Pull the live header and footer out of index.html instead of retyping them, so a
    discovery page's nav/footer never drifts from the real site (docs/DESIGN.md: copy the
    frame, don't retype it). Drop aria-current, since no nav item is "current" on this page,
    the same choice already made for profile.html. Links stay root-relative here; the page
    writer applies relocate() once, over the whole assembled page."""
    source = (ROOT / 'index.html').read_text()
    header = re.search(r'<header class="header">.*?</header>', source, re.S).group(0)
    footer = re.search(r'<footer class="footer">.*?</footer>', source, re.S).group(0)
    return header.replace(' aria-current="page"', ''), footer


def run_catalog_ui(items):
    """Render each record's source links, source-check disclosure and correction-issue link with the same
    assets/catalog-ui.js the live pages use (one Node process for all records), so a discovery
    page never repeats that wording or that URL-building logic in a second, Python copy."""
    cites_path = ROOT / 'data/citations.json'
    snapshot = json.loads(cites_path.read_text()) if cites_path.exists() else {}
    cites = snapshot.get('records', {})
    items = [dict(r, citation=dict(cites[r['id']], checked=snapshot.get('checked'))) if r['id'] in cites else r for r in items]
    script = ("require(process.argv[1]);"
              "const items = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "const out = {};"
              "for (const r of items) out[r.id] = {links: CatalogUI.sourceLinks(r), details: CatalogUI.sourceDetails(r), status: CatalogUI.sourceBadge(r), correction: CatalogUI.correctionUrl(r)};"
              "process.stdout.write(JSON.stringify(out));")
    result = subprocess.run(['node', '-e', script, str(ROOT / 'assets/catalog-ui.js')],
                            input=json.dumps(items), capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


CARD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="{css}">
</head><body class="og-card">
<div class="og-frame">
  <p class="og-brand"><svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#f2f6ff"/><path d="M8 24v-6M12 24v-11M16 24v-15M20 24v-8M24 24v-4" stroke="#12367e" stroke-width="2.6" stroke-linecap="round"/></svg>{site}</p>
  <h1>{title}</h1>
  <p class="og-meta">{meta}</p>
  {score_row}
</div></body></html>"""


def card_html(css, title, meta, score_row=''):
    return CARD.format(css=css, site=SITE, title=title, meta=meta, score_row=score_row)


def screenshot(page, out):
    from PIL import Image  # Only needed when a card is actually rendered, so CI parity checks skip it.
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                    '--force-device-scale-factor=1', '--window-size=1200,630',
                    '--virtual-time-budget=2000', f'--screenshot={out}', page.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Cards are flat two-color layouts: a 32-color palette looks the same and is about 3x smaller.
    with Image.open(out) as image:
        card = image.convert('RGB').quantize(32, method=Image.Quantize.FASTOCTREE)
    card.save(out, optimize=True)


def render_cards(items, force, reuse_images=False):
    if force and reuse_images:
        raise ValueError('Forced rendering and image reuse are incompatible')
    out_dir = ROOT / 'og'
    out_dir.mkdir(exist_ok=True)
    manifest_path = out_dir / 'card-hashes.json'
    hashes = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    assets = (ROOT / 'styles.css').read_bytes() + b''.join(
        p.read_bytes() for p in sorted((ROOT / 'assets/fonts').glob('*.woff2')))
    css = (ROOT / 'styles.css').as_uri()
    cards = [('default', card_html(css, 'Scientific discoveries enabled by AI',
                                   'Tracked from official announcements since 2020'))]
    for d in items:
        row = (f'<p class="og-score"><span class="metro"><i style="width:{score(d)}%"></i></span> '
               f'Relevance {score(d)} · {esc(d["field"])}</p>')
        cards.append((d['id'], card_html(css, esc(clip(d['title'], 150)),
                      f'{esc(clip(d["organization"], 90))} · {nice_date(d["publication_date"])}', row)))
    updated = {}
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / 'card.html'
        for name, content in cards:
            digest = hashlib.sha256(content.replace(css, 'styles.css').encode() + assets).hexdigest()
            updated[name] = digest
            out = out_dir / f'{name}.png'
            if reuse_images:
                if not out.is_file():
                    raise ValueError(f'Cannot reuse missing image: {name}')
                continue
            if force or not out.exists() or hashes.get(name) != digest:
                page.write_text(content)
                print(f'card {name}', file=sys.stderr)
                screenshot(page, out)
    manifest_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + '\n')


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://cloudflareinsights.com; object-src 'none'; base-uri 'self'; form-action 'self'">
<script type="speculationrules">{{"prerender":[{{"where":{{"and":[{{"href_matches":"/*"}},{{"not":{{"href_matches":"/data/*"}}}},{{"not":{{"href_matches":"/api/*"}}}},{{"not":{{"href_matches":"/og/*"}}}},{{"not":{{"href_matches":"/*.xml"}}}},{{"not":{{"href_matches":"/*.txt"}}}}]}},"eagerness":"moderate"}}]}}</script><!-- Cloudflare Web Analytics --><script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token": "04bfc0ca5b5e4460b4c8ee6bb5055925"}}'></script><!-- End Cloudflare Web Analytics -->
<script>document.documentElement.classList.add("js")</script><!-- lets the section menu collapse behind its button on narrow screens -->
<title>{title} · {site}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{base}{path}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{site}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{base}{path}">
<meta property="og:image" content="{base}og/{img}.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{imgalt}">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image:alt" content="{imgalt}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#12367e">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2312367e'/%3E%3Cpath d='M8 24v-6M12 24v-11M16 24v-15M20 24v-8M24 24v-4' stroke='%23f2f6ff' stroke-width='2.6' stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preload" href="assets/fonts/schibsted-grotesk-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="styles.css">
<link rel="stylesheet" href="__I18N_CSS__">
{jsonld}
</head>
<body class="static-page">
{header}

<section class="banda banda-bassa" aria-labelledby="titolo-pagina">
  <div class="wrap">
    <h1 id="titolo-pagina">{title}</h1>
    <p class="lead">{lead}</p>
  </div>
</section>

<main>
  <section class="sez"><div class="wrap">
    {h2}<div class="piatto">{article}</div>
    <p class="sez-sub">{more}</p>
  </div></section>{extra}
</main>

{footer}
</body>
</html>
"""


CREATOR = {'@type': 'Person', 'name': 'Marcello Pichini', 'url': 'https://github.com/marcello-pichini'}
PUBLISHER = {'@type': 'Organization', '@id': BASE + '#organization', 'name': SITE, 'url': BASE,
             'sameAs': ['https://github.com/marcello-pichini/ai-science-tracker', 'https://doi.org/10.5281/zenodo.24217686',
                        'https://huggingface.co/datasets/marcello-pichini/ai-science-tracker',
                        'https://www.linkedin.com/company/aisciencetracker/']}
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'
DATASET_ID = BASE + 'dataset.html#scientific-dataset'
SECURITY_DATASET_ID = BASE + 'dataset.html#security-dataset'


def jsonld(data):
    """Inline JSON-LD; '<' is escaped so record text can never close the script element."""
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return f'<script type="application/ld+json">\n{text}\n</script>'


def breadcrumb(name, path):
    return {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'AI Science Tracker', 'item': BASE},
        {'@type': 'ListItem', 'position': 2, 'name': name, 'item': BASE + path}]}


def discovery_jsonld(d):
    # WebPage plus an Article for the catalog record (our summary). This is not the paper itself,
    # so it is not a ScholarlyArticle. datePublished is the source announcement date.
    url = f'{BASE}share/{d["id"]}.html'
    work = {'@type': 'Article', 'name': d['title'], 'headline': clip(d['title'], 110), 'author': CREATOR, 'publisher': PUBLISHER, 'abstract': clip(d['summary'], 300),
            'datePublished': d['publication_date'], 'inLanguage': 'en', 'url': url, 'keywords': d['field'],
            'isBasedOn': d['source_url']}
    data = {'@context': 'https://schema.org/', '@type': 'WebPage', 'name': d['title'], 'description': clip(d['summary'], 300),
            'url': url, 'inLanguage': 'en', 'license': LICENSE_URL, 'creator': CREATOR, 'publisher': PUBLISHER,
            'mainEntity': work, 'isPartOf': {'@id': DATASET_ID},
            'breadcrumb': breadcrumb(d['title'], f'share/{d["id"]}.html'),
            'about': {'@type': 'Thing', 'name': d['title']}, 'isBasedOn': d['source_url']}
    if d['paper_url']:
        data['citation'] = d['paper_url']
        work['sameAs'] = d['paper_url']
    return jsonld(data)


def profile_jsonld(name, desc, path, organization=False, security=False, page_type='CollectionPage'):
    data = {'@context': 'https://schema.org/', '@type': page_type, 'name': name, 'description': desc,
            'url': BASE + path, 'inLanguage': 'en', 'license': LICENSE_URL, 'creator': CREATOR, 'publisher': PUBLISHER,
            'isPartOf': {'@id': DATASET_ID},
            'breadcrumb': breadcrumb(name, path)}
    if security:
        data['isPartOf'] = {'@id': SECURITY_DATASET_ID}
    if organization:
        data['about'] = {'@type': 'Organization', 'name': name}
    return jsonld(data)


# Letters NFKD does not decompose; anything else outside ASCII still becomes a separator.
SLUG_LETTERS = str.maketrans({'ø': 'o', 'ß': 'ss', 'æ': 'ae', 'œ': 'oe', 'ł': 'l', 'đ': 'd', 'ı': 'i', 'þ': 'th', 'ð': 'd', 'ħ': 'h'})


def slug(text):
    # Accented letters keep their base letter ("Skåne" -> "skane"), so a slug never loses letters.
    folded = ''.join(c for c in unicodedata.normalize('NFKD', text.lower().translate(SLUG_LETTERS)) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '-', folded).strip('-')


def legacy_slug(text):
    """Slug used before 27 November 2026, which dropped accented letters; kept only to redirect old URLs."""
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def safe_url(u):
    return u if re.match(r'^https?://', u or '') else '#'


def discovery_article(d, fam, ui, link_title=False, archived=False):
    """Same fields and markup as index.html's voce(), minus JS-only copy controls."""
    p = score(d)
    family = (f'<p class="modello">Family {esc(fam["name"])}: <a href="profiles/family-{quote(fam["id"])}.html">profile</a> '
              f'&middot; <a href="models.html#fam-{esc(fam["id"])}">models page</a></p>') if fam else ''
    tech = f'<p class="tech"><span>Technology:</span> {esc(d["ai_technology"])}</p>' if d['ai_technology'] else ''
    title_html = f'<a href="share/{esc(d["id"])}.html">{esc(d["title"])}</a>' if link_title else esc(d['title'])
    organization = esc(d['organization']) if archived else f'<a href="profiles/org-{slug(lead_org(d["organization"]))}.html">{esc(d["organization"])}</a>'
    return f"""<article class="voce" id="{esc(d['id'])}">
    <div class="voce-meta"><time datetime="{esc(d['publication_date'])}">{esc(nice_date(d['publication_date']))}</time>{organization}</div>
    <h3>{title_html}</h3>
    {ui['status']}
    <p class="sommario"><b>{"Finding / tested result" if d.get("evidence", {}).get("tested") == d["summary"] else "Finding"}:</b> {esc(d['summary'])}</p>
    {tech}
    {family}
    <div class="voce-footer">
      <span class="punteggio" title="Impact {d['relevance']['impact']}/5, validation {d['relevance']['validation']}/5, novelty {d['relevance']['novelty']}/5">Editorial relevance {p}<span class="metro" aria-hidden="true"><i style="width:{p}%"></i></span></span>
      <span class="etich">{esc(d['field'])}</span>
      <span class="collegamenti">{ui['links']} <a class="correction-link" href="{esc(ui['correction'])}" rel="noopener">Suggest a correction</a></span>
    </div>
    {ui['details']}
  </article>"""


TITLE_MAX = 60
STOP_WORDS = frozenset('''the and for with from into that this these those than then their there were was are has have
had not but its new using used use via based model models data study studies result results shows show showed
identifies identified predicts predicted helps help can more most first after over under between across within
which while when where also two three four five one all any per out who how what our its such'''.split())
# Single-discovery organization pages mostly repeat their discovery page: keep them reachable but noindex.
ORG_INDEX_MIN = 2
PROFILE_FULL_CARDS = 100
RELATED_LIMIT = 5
TOPIC_THRESHOLD = 0.12


def search_title(d, limit=TITLE_MAX):
    """Short <title> for search results; the H1, og:title and JSON-LD keep the full title."""
    if d.get('search_title'):
        return d['search_title']
    # The suffix tells searchers this is an AI-discovery review, not the paper itself.
    suffix = ' · AI discovery' if d['field'] in ('other', 'multidisciplinary') else f' · AI in {d["field"]}'
    if len(d['title']) + len(suffix) <= limit:
        return d['title'] + suffix
    if len(d['title']) <= limit:
        return d['title']
    return clip(d['title'], limit - len(suffix)) + suffix


def topic_words(row):
    text = f'{row["title"]} {row["summary"]} {row["ai_technology"]}'.lower()
    return frozenset(w for w in re.findall(r'[a-z][a-z0-9-]{2,}', text) if w not in STOP_WORDS)


def topic_similarity(a, b):
    return len(a & b) / ((len(a) * len(b)) ** 0.5) if a and b else 0.0


def related_section(d, candidates, families):
    """Prefer recorded links, then exact catalog context, then similar wording in the same field."""
    current_id = d['id']
    words = topic_words(d)
    outgoing = {link['target_id'] for link in d.get('relationships', [])}
    affiliation = canonical_organization(d['organization'])
    current_org = affiliation['label'] if affiliation['kind'] != 'unknown affiliation' else None
    current_date = datetime.date.fromisoformat(d['publication_date'])
    technology = d['ai_technology'].strip().casefold()
    ranked = []
    for row, org, day, incoming, tech, other_words in candidates:
        other_id = row['id']
        if other_id == current_id:
            continue
        documented = other_id in outgoing or current_id in incoming
        shared_family = bool(families.get(current_id, set()) & families.get(other_id, set()))
        same_field = d['field'] == row['field']
        same_technology = bool(technology and technology == tech)
        same_org = current_org == org
        similarity = topic_similarity(words, other_words) if same_field else 0.0
        exact = any((documented, shared_family, same_technology, same_field and same_org))
        if not exact and similarity < TOPIC_THRESHOLD:
            continue
        reason = ('Documented relationship' if documented else 'Shared model family' if shared_family
                  else 'Same recorded technology' if same_technology
                  else 'Same field and first-listed affiliation' if same_field and same_org
                  else 'Similar topic in the same field')
        key = (not documented, not (same_field and (shared_family or same_technology)),
               not shared_family, not same_technology, not (same_field and same_org),
               not same_field, not exact, -round(similarity, 6), abs((current_date - day).days), other_id)
        ranked.append((key, row, reason))
    if not ranked:
        return ''
    links = ''.join(f'<li><a href="share/{quote(row["id"])}.html">{esc(row["title"])}</a>'
                    f' &middot; {esc(nice_date(row["publication_date"]))} · {reason}</li>'
                    for _, row, reason in sorted(ranked)[:RELATED_LIMIT])
    return ('\n  <section class="sez"><div class="wrap prosa"><h2>Related catalog entries</h2>'
            '<p>Links use documented relationships where available, plus shared catalog context. '
            'A shared topic or model family does not establish a scientific dependency.</p>'
            f'<ul>{links}</ul></div></section>')


def write_discovery_pages(items, models, images, archived=False, related_items=None, plain=None):
    """Each page is a full, self-canonical page in the shared frame, indexable without
    JavaScript (IMP-011) — replacing the earlier noindex/meta-refresh stub."""
    out = ROOT / 'share'
    out.mkdir(exist_ok=True)
    header, footer = site_frame()
    fam_by_discovery = {}
    families_by_discovery = {}
    for f in models['families']:
        for did in f['discoveries']:
            fam_by_discovery.setdefault(did, f)
            families_by_discovery.setdefault(did, set()).add(f['id'])
    candidates = [(row, lead_org(row['organization']), datetime.date.fromisoformat(row['publication_date']),
                   {link['target_id'] for link in row.get('relationships', [])}, row['ai_technology'].strip().casefold(),
                   topic_words(row))
                  for row in (items if related_items is None else related_items)]
    fields = {row['field'] for row, *_ in candidates}
    years = {row['publication_date'][:4] for row, *_ in candidates}
    budget = TITLE_MAX - len('Archived: ') if archived else TITLE_MAX
    titles = {d['id']: search_title(d, budget) for d in items}
    seen = {}
    for t in titles.values():
        seen[t] = seen.get(t, 0) + 1
    for d in items:
        if seen[titles[d['id']]] > 1 and not d.get('search_title'):
            titles[d['id']] = clip(d['title'], budget - 7) + f' ({d["publication_date"][:4]})'
    seen = {}
    for t in titles.values():
        seen[t] = seen.get(t, 0) + 1
    for d in items:
        if seen[titles[d['id']]] > 1 and not d.get('search_title'):
            titles[d['id']] = clip(d['title'], budget - 10) + f' ({d["publication_date"][:7]})'  # month separates same-year twins
    ui = run_catalog_ui(items)
    for d in items:
        has_image = images or (ROOT / 'og' / f'{d["id"]}.png').is_file()
        article = discovery_article(d, fam_by_discovery.get(d['id']), ui[d['id']], archived=archived)
        more = ('<a href="/">Browse the current catalog</a>.' if archived else
                f'<a href="/#discovery={quote(d["id"])}">Open in the full catalog</a> for filters, charts and related discoveries.')
        lead = f'{esc(d["organization"])} &middot; {esc(nice_date(d["publication_date"]))} &middot; {esc(d["field"])}'
        if d['field'] in fields:
            more += f' <a href="profiles/field-{slug(d["field"])}.html">Browse {esc(d["field"])} discoveries</a>.'
        year = d['publication_date'][:4]
        if year in years and not archived:
            more += f' <a href="profiles/year-{year}.html">Browse {year} discoveries</a>.'
        # The card names only the first family; link the others so their profiles are not orphaned.
        other_families = [f for f in models['families'] if d['id'] in f['discoveries'] and f is not fam_by_discovery.get(d['id'])]
        if other_families and not archived:
            more += ' Also linked model families: ' + ', '.join(
                f'<a href="profiles/family-{quote(f["id"])}.html">{esc(f["name"])}</a>' for f in other_families) + '.'
        if d['id'] in DOSSIER_IDS and not archived:
            topic, section = DOSSIER_IDS[d['id']]
            more += f' <a href="{topic}-dossier.html#{section}">Read the {topic} evidence dossier</a>.'
        if archived:
            lead = f'Archived catalog entry &middot; {lead}'
        short = '' if archived else plain_short_version(d, plain or {}, has_image)
        specialists = ('<h2>For specialists</h2>' if plain_text(plain or {}, d['id']) and not archived
                       else '<h2 class="vis-nascosto">Discovery</h2>')
        page = PAGE.format(title=esc(d['title']), site=SITE, desc=esc(describe(d['summary'], lead=d['title'])), base=BASE,
                           path=f'share/{d["id"]}.html', img=d['id'] if has_image else 'default',
                           imgalt=esc(f'Preview card: {d["title"]}') if has_image else DEFAULT_ALT, jsonld=discovery_jsonld(d),
                           h2=short + specialists, more=more, extra=related_section(d, candidates, families_by_discovery),
                           header=header, footer=footer, lead=lead, article=article)
        page = page.replace(f'<title>{esc(d["title"])} · {SITE}</title>',
                            f'<title>{"Archived: " if archived else ""}{esc(titles[d["id"]])}</title>', 1)
        (out / f'{d["id"]}.html').write_text('\n'.join(line.rstrip() for line in relocate(page).splitlines()) + '\n')


def releases_table(models):
    rows = ''.join(f"""<tr><td data-l="Date"><time datetime="{esc(m['date'])}">{esc(nice_date(m['date']))}</time></td>
    <td data-l="Model" class="nome">{f'<a href="{esc(safe_url(m["link"]))}" rel="noopener">{esc(m["name"])}</a>' if m.get('link') else esc(m['name'])}</td>
    <td data-l="Access">{esc(m.get('access') or '')}</td></tr>""" for m in sorted(models, key=lambda m: m['date'], reverse=True))
    return f"""
  <section class="sez"><div class="wrap">
    <h2>{len(models)} model release{'' if len(models) == 1 else 's'}</h2>
    <p class="sez-sub">Epoch AI data (CC BY 4.0), newest first. A discovery is attributed to a model family, not to a specific release.</p>
    <table class="tab-rilasci"><thead><tr><th>Date</th><th>Model</th><th>Access</th></tr></thead><tbody>{rows}</tbody></table>
  </div></section>""" if models else ''


def family_summary(rows, name):
    """The same stored-link scope and deterministic examples as FamilyOutcomes."""
    def members(records):
        return '<ul>' + ''.join(f'<li><a href="/#discovery={quote(d["id"])}">{esc(d["title"])}</a></li>' for d in records) + '</ul>' if records else '<p>No scientific uses are linked in this catalog.</p>'

    def test_context(d):
        value = d.get('evidence', {}).get('test_type')
        return 'Not annotated in this catalog' if not value else 'Test context unspecified in annotation' if value == 'not reported' else value

    def groups(title, key):
        return f'<h3>{title}</h3>' + ''.join(f'<details><summary>{esc(label)} · {len(group)} linked records</summary>{members(group)}</details>' for label, group in ((label, [d for d in rows if key(d) == label]) for label in sorted({key(d) for d in rows})))

    annotated = sum(bool(d.get('evidence')) for d in rows)
    reviewed = sum(bool(d.get('source_review', {}).get('date') and d.get('source_review', {}).get('scope')) for d in rows)
    # Stable two-pass sorting keeps equal-date examples in ID order.
    examples = sorted(sorted(rows, key=lambda d: d['id']), key=lambda d: d['publication_date'], reverse=True)[:3]
    return f'<section aria-label="Represented scientific uses"><h2>Where {esc(name)} appears in the catalog</h2><p><b>Evidence annotations:</b> {annotated}/{len(rows)} linked records. <b>Structured review date and scope:</b> {reviewed}/{len(rows)}. Missing review metadata does not prove a source was never checked.</p><details class="source-details"><summary>Why linked?</summary><p>These associations match family names in discovery titles and technology text. They are not verified model-version assignments or causal attribution. Missing links do not establish absence of use. A record may link to multiple families.</p></details>' + (groups('Represented fields', lambda d: d['field']) + groups('Test contexts', test_context) + groups('Annotation coverage', lambda d: 'Evidence annotation present' if d.get('evidence') else 'Not annotated in this catalog') if rows else '<p>No scientific uses are linked in this catalog.</p>') + '<h3>Examples</h3><p>Up to three linked records, newest publication date first, then stable ID. This selection is not a ranking.</p>' + members(examples) + '</section>'


def family_affiliations(rows):
    """Preserve first-affiliation profile links outside the concise family lead."""
    names = sorted({lead_org(d['organization']) for d in rows})
    links = ''.join(f'<li><a href="profiles/org-{slug(name)}.html">{esc(name)}</a></li>' for name in names)
    return (f'<h2>First-listed affiliations</h2><details class="source-details">'
            f'<summary>{len(names)} first-affiliation groups in linked records</summary>'
            '<p>Grouping uses the first listed affiliation; complete source labels remain on each entry.</p>'
            f'<ul class="elenco-profili">{links}</ul></details>') if names else ''


def collection_summary(rows, title, by_year=False):
    """Source-derived orientation and cross-links, without completeness or trend claims."""
    counts = Counter(d['field'] if by_year else d['publication_date'][:4] for d in rows)
    links = []
    for key, count in sorted(counts.items(), reverse=not by_year):
        path = f'profiles/field-{slug(key)}.html' if by_year else f'profiles/year-{key}.html'
        links.append(f'<li><a href="{path}">{esc(key)}</a> · {count} entries in this selection</li>')
    annotated = sum(bool(d.get('evidence')) for d in rows)
    dates = sorted(d['publication_date'] for d in rows)
    dimension = 'field' if by_year else 'year'
    return (f'<section class="prosa" aria-label="Collection overview"><h2>About {esc(title)}</h2>'
            f'<p>This selection contains {len(rows)} catalog entries dated {nice_date(dates[0])} to {nice_date(dates[-1])}. '
            f'{annotated} include structured evidence annotations describing reported tests, the AI contribution and remaining limits. '
            'Missing annotations mean those details have not been structured here, not that a study lacks evidence.</p>'
            '<p>Dates follow the catalog publication policy. Coverage is selected and incomplete; entries can overlap or describe several results. '
            'Counts do not measure independent discoveries, clinical benefit or worldwide research output. '
            '<a href="methodology.html">Read the selection and evidence policy</a> or '
            '<a href="profiles/catalog-evidence.html">compare catalog coverage by year and field</a>.</p>'
            f'<details><summary>Explore this selection by {dimension}</summary><p>Counts refer to this selection; '
            f'each link opens the full {dimension} collection.</p><ul>{"".join(links)}</ul></details></section>')


def write_profile_pages(items, models, archived=()):
    """Static, indexable organization and model-family profiles (IMP-011 extension). Organization
    pages omit model releases: profile.html maps labs to Epoch organizations with an alias list
    that lives only in its script, and copying it here would let the two drift."""
    out = ROOT / 'profiles'
    out.mkdir(exist_ok=True)
    header, footer = site_frame()
    fam_by_discovery = {}
    for f in models['families']:
        for did in f['discoveries']:
            fam_by_discovery.setdefault(did, f)
    ui = run_catalog_ui(items)
    by_id = {d['id']: d for d in items}
    by_org = {}
    for d in sorted(items, key=lambda d: d['publication_date'], reverse=True):
        by_org.setdefault(lead_org(d['organization']), []).append(d)
    pages = []
    aliases = {}
    for d in items:
        legacy_names = {d['organization'].split(';')[0].strip(), d['organization'].replace(' and ', ',').split(',')[0].strip(),
                        re.split(r'[,;]| and ', d['organization'], flags=re.I)[0].strip()}
        new = slug(lead_org(d['organization']))
        for legacy in legacy_names | {lead_org(d['organization']), d['organization'].split(';')[0].strip()}:
            for old in {slug(legacy), legacy_slug(legacy)}:
                if old != new:
                    aliases.setdefault(old, set()).add(new)

    def years(rows):
        ys = sorted(d['publication_date'][:4] for d in rows)
        return ys[0] if ys[0] == ys[-1] else f'{ys[0]} to {ys[-1]}'

    def plural(n, one, many):
        return f'{n} {one if n == 1 else many}'

    def emit(name, title, lead, desc, rows, path, interactive, extra='', organization=False, label='interactive profile', before='', noindex=False, head_title=None):
        # Full cards made field/year pages exceed 9 MB; older rows keep a crawlable link to their own page.
        articles = ''.join(discovery_article(d, fam_by_discovery.get(d['id']), ui[d['id']], link_title=True) for d in rows[:PROFILE_FULL_CARDS])
        if len(rows) > PROFILE_FULL_CARDS:
            articles += ('<h2>Earlier discoveries</h2><ul class="elenco-profili">' + ''.join(
                f'<li><a href="share/{quote(d["id"])}.html">{esc(d["title"])}</a> ({d["publication_date"]})</li>'
                for d in rows[PROFILE_FULL_CARDS:]) + '</ul>')
        if len(desc) < DESC_MIN:
            desc += ' Each entry states the AI role, the evidence and its limits.'
        desc = clip(desc, 160)
        purpose = 'the timeline' if label == 'interactive profile' else 'charts and filters'
        more = f'<a href="{interactive}">Open the {label}</a> for {purpose}, or <a href="profiles/index.html">browse all organizations and model families</a>.'
        page = PAGE.format(title=esc(title), site=SITE, desc=esc(desc), base=BASE, path=path, img='default', imgalt=DEFAULT_ALT,
                           header=header, footer=footer, lead=lead, article=articles, more=more, extra=extra,
                           h2=before + '<h2 class="vis-nascosto">Discoveries</h2>', jsonld=profile_jsonld(title, desc, path, organization))
        if head_title and len(head_title) <= 60:
            # Search titles say what the page offers; a bare lab name loses the click to the lab's own site.
            page = page.replace(f'<title>{esc(title)} · ', f'<title>{esc(head_title)} · ', 1)
        if noindex:
            page = page.replace('<link rel="canonical"', '<meta name="robots" content="noindex, follow">\n<link rel="canonical"', 1)
        (ROOT / path).write_text('\n'.join(line.rstrip() for line in relocate(fit_title(page)).splitlines()) + '\n')
        pages.append(path)

    slugs = {}
    for name, rows in by_org.items():
        assert slugs.setdefault(slug(name), name) == name, f'organization slug collision: {name}'
        known = canonical_organization(rows[0]['organization'])['kind'] != 'unknown affiliation'
        source = f'from {name}' if known else 'whose sources report no author affiliation'
        head = f'{name}: {plural(len(rows), "AI science discovery", "AI science discoveries")}' if known else f'Unattributed AI science: {plural(len(rows), "discovery", "discoveries")}'
        emit(name, name, f'{plural(len(rows), "discovery", "discoveries")} from {years(rows)}',
             describe(f'{plural(len(rows), "AI-enabled discovery", "AI-enabled discoveries")} {source}, {"with" if len(rows) == 1 else "each with"} the original paper, AI role and evidence limits. Latest: {rows[0]["title"]}.', 160),
             rows, f'profiles/org-{slug(name)}.html', f'profile.html?org={quote(name)}', organization=known,
             noindex=len(rows) < ORG_INDEX_MIN, head_title=head)
    archived_orgs = {}
    for d in archived:
        legacy = slug(d['organization'].replace(' and ', ',').split(',')[0].strip())
        previous = slug(re.split(r'[,;]| and ', d['organization'], flags=re.I)[0].strip())
        lead = slug(lead_org(d['organization']))
        old_forms = {legacy_slug(d['organization'].replace(' and ', ',').split(',')[0].strip()),
                     legacy_slug(re.split(r'[,;]| and ', d['organization'], flags=re.I)[0].strip()), legacy_slug(lead_org(d['organization']))}
        for old in {legacy, previous, lead} | old_forms:
            if old not in slugs:
                target = f'org-{lead}.html' if lead in slugs else f'../share/{quote(d["id"])}.html'
                archived_orgs.setdefault(old, set()).add(target)
    for old, targets in aliases.items():
        if old not in slugs:
            archived_orgs.setdefault(old, set()).update(f'org-{new}.html' for new in targets)

    def redirect(path, targets):
        # A speculative legacy alias cannot have existed as a file beyond this limit.
        if len(path.encode('utf-8')) > 255:
            return
        target = next(iter(targets)) if len(targets) == 1 else 'index.html'
        canonical = BASE + (target[3:] if target.startswith('../') else f'profiles/{target}')
        title = 'Organization profile moved' if path.startswith('org-') else 'Model family profile moved'
        icon = next(line for line in PAGE.splitlines() if 'rel="icon"' in line)
        (out / path).write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
{icon}
<link rel="canonical" href="{canonical}"><meta http-equiv="refresh" content="0; url={target}"></head>
<body><p>This profile has moved to <a href="{target}">the preserved page</a>.</p></body></html>
''')
        pages.append(f'profiles/{path}')

    for old, targets in sorted(archived_orgs.items()):
        redirect(f'org-{old}.html', targets)
    active_families = set()
    for fam in sorted(models['families'], key=lambda f: f['id']):
        rows = sorted((by_id[i] for i in fam['discoveries'] if i in by_id), key=lambda d: d['publication_date'], reverse=True)
        if not rows:
            continue
        active_families.add(fam['id'])
        rel = [m for m in models.get('models', []) if m.get('family') == fam['id']]
        description = f'{plural(len(rows), "AI-enabled scientific discovery", "AI-enabled scientific discoveries")} linked to the {fam["name"]} model family.'
        dossier = ''
        if fam['id'] == 'alphafold':
            description = 'Browse scientific discoveries and model releases linked to AlphaFold, and read the evidence dossier.'
            dossier = ('<p id="alphafold-evidence"><a href="alphafold-dossier.html">'
                       'Read the AlphaFold evidence dossier</a>.</p>')
        emit(fam['name'], fam['name'], f'{plural(len(rows), "discovery", "discoveries")} name this family, {years(rows)}, across {len({d["field"] for d in rows})} scientific fields. Links are name-based family associations; exact versions and causal attribution are not verified.',
             description,
             rows, f'profiles/family-{quote(fam["id"])}.html', f'profile.html?family={quote(fam["id"])}', releases_table(rel), before=dossier + family_affiliations(rows) + family_summary(rows, fam['name']),
             head_title=f'{fam["name"]}: {plural(len(rows), "scientific discovery", "scientific discoveries")}')
    for fid, ids in discovery_links(archived).items():
        if ids and fid not in active_families:
            redirect(f'family-{quote(fid)}.html', {f'../share/{quote(did)}.html' for did in ids})
    # Field and year collections answer searches such as "AI discoveries in biology" or "AI discoveries 2025".
    by_field, by_year = {}, {}
    for d in sorted(items, key=lambda d: d['publication_date'], reverse=True):
        by_field.setdefault(d['field'], []).append(d)
        by_year.setdefault(d['publication_date'][:4], []).append(d)
    for field, rows in sorted(by_field.items()):
        title = f'AI discoveries in {field}'
        overview = collection_summary(rows, title)
        if field == 'materials' and {'2023-11-gnome', '2023-11-a-lab', '2020-05-hob2-magnetocaloric-effect'} <= {d['id'] for d in rows}:
            title = 'AI materials discoveries: predictions and experiments'
            overview = ('<section class="prosa"><h2>From prediction to physical evidence</h2>'
                        '<ul><li><a href="share/2023-11-gnome.html">GNoME</a> used a graph neural network to predict crystal structures '
                        'and estimate stability. The project reports that other laboratories synthesized some of the predicted structures.</li>'
                        '<li><a href="share/2023-11-a-lab.html">A-Lab</a> used an automated laboratory to make compounds from computed targets. '
                        'The catalog record links the correction and explains where the diffraction evidence remained inconclusive.</li>'
                        '<li><a href="share/2020-05-hob2-magnetocaloric-effect.html">The HoB₂ magnetocaloric study</a> used machine learning '
                        'to select a known compound. The study reports measurements of its magnetic entropy change under an applied field.</li></ul>'
                        '<p>These studies illustrate distinct steps. A calculation estimates stability, synthesis produces a sample, '
                        'and a property measurement tests a defined characteristic under stated conditions. '
                        'For claims about performance, check which property was measured and what it was compared with.</p></section>') + overview
        math_examples = {'2024-07-alphaproof-imo', '2026-02-congettura-fel', '2026-03-alphaevolve-ramsey'}
        if field == 'mathematics' and math_examples <= {d['id'] for d in rows}:
            overview = (
                '<section class="prosa"><h2>What has AI helped discover in mathematics?</h2>'
                '<p>AI systems can solve competition problems, help formalize proofs and search for constructions that improve mathematical bounds. '
                'Each task has a different way to check the result.</p><dl>'
                '<dt><a href="share/2024-07-alphaproof-imo.html">Competition benchmark: AlphaProof and AlphaGeometry 2</a></dt>'
                '<dd>Two mathematicians graded the solutions against International Mathematical Olympiad criteria. '
                'The team translated problems into formal language manually, and some solutions took up to three days.</dd>'
                '<dt><a href="share/2026-02-congettura-fel.html">Formal proof: the Fel conjecture</a></dt>'
                '<dd>AxiomMath reports a proof checked in Lean. The report describes one case and identifies dependence on the available Mathlib library.</dd>'
                '<dt><a href="share/2026-03-alphaevolve-ramsey.html">Improved bounds: AlphaEvolve and Ramsey numbers</a></dt>'
                '<dd>The authors report computational constructions that improve lower bounds for Ramsey numbers. '
                'A lower bound constrains the possible value. The exact number remains a separate question.</dd>'
                '</dl><p>Follow the linked records for sources and the limits of each check.</p></section>'
            ) + overview
        topics = {DOSSIER_IDS[d['id']][0] for d in rows if d['id'] in DOSSIER_IDS}
        if field in DOSSIERS:
            topics.add(field)
        if topics:
            links = ' · '.join(f'<a href="{topic}-dossier.html">Read the {topic} evidence dossier</a>'
                               for topic in sorted(topics))
            overview = f'<p class="prosa">{links}.</p>' + overview
        emit(field, title, f'{plural(len(rows), "discovery", "discoveries")} from {years(rows)}',
             f'{plural(len(rows), "scientific discovery", "scientific discoveries")} in {field} made with AI, {years(rows)}, each linked to its original source.',
             rows, f'profiles/field-{slug(field)}.html', f'/?field={quote(field)}', label='filtered catalog',
             before=overview)
    for year, rows in sorted(by_year.items(), reverse=True):
        emit(year, f'AI discoveries in {year}', f'{plural(len(rows), "discovery", "discoveries")} announced in {year}',
             f'{plural(len(rows), "scientific discovery", "scientific discoveries")} made with AI and announced in {year}, each linked to its original source.',
             rows, f'profiles/year-{year}.html', f'/?year={year}', label='filtered catalog',
             before=collection_summary(rows, f'AI discoveries in {year}', by_year=True))
    topics = ''.join(f'<li><a href="profiles/field-{slug(f)}.html">{esc(f)}</a> ({len(r)})</li>' for f, r in sorted(by_field.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    yearly = ''.join(f'<li><a href="profiles/year-{y}.html">{y}</a> ({len(r)})</li>' for y, r in sorted(by_year.items(), reverse=True))
    unknown_groups = {n: rows for n, rows in by_org.items() if canonical_organization(rows[0]['organization'])['kind'] == 'unknown affiliation'}
    labs = ''.join(f'<li><a href="profiles/org-{slug(n)}.html">{esc(n)}</a> ({len(r)})</li>' for n, r in sorted(by_org.items(), key=lambda kv: (-len(kv[1]), kv[0])) if n not in unknown_groups)
    fams = ''.join(f'<li><a href="profiles/family-{quote(f["id"])}.html">{esc(f["name"])}</a> ({len(f["discoveries"])})</li>' for f in sorted(models['families'], key=lambda f: (-len(f['discoveries']), f['name'])) if f['discoveries'])
    unknown_links = ''.join(f'<li><a href="profiles/org-{slug(n)}.html">{esc(n)}</a> ({len(rows)})</li>' for n, rows in unknown_groups.items())
    directory = f'<h2>Fields</h2><ul class="elenco-profili">{topics}</ul><h2>Years</h2><ul class="elenco-profili">{yearly}</ul><h2>Organizations</h2><ul class="elenco-profili">{labs}</ul><h2>Unknown affiliation</h2><p>These entries do not establish an institution; original author and source labels are preserved.</p><ul class="elenco-profili">{unknown_links}</ul><h2>Model families</h2><ul class="elenco-profili">{fams}</ul>'
    page = PAGE.format(title='AI discoveries by field, year, lab and model family', site=SITE, desc='Browse source-linked AI scientific discoveries by discipline, publication year, organization and model family.', base=BASE,
                       path='profiles/index.html', img='default', imgalt=DEFAULT_ALT, header=header, footer=footer,
                       jsonld=profile_jsonld('AI discoveries by field, year, lab and model family', 'Browse source-linked AI scientific discoveries by discipline, publication year, organization and model family.', 'profiles/index.html'),
                       lead=f'{len(by_org) - len(unknown_groups)} organizations and {len([f for f in models["families"] if f["discoveries"]])} model families', article=directory,
                       more='<a href="profile.html">Open the interactive directory</a>.', extra='', h2='')
    (ROOT / 'profiles/index.html').write_text('\n'.join(line.rstrip() for line in relocate(fit_title(page)).splitlines()) + '\n')
    pages.append('profiles/index.html')
    current = set(pages)
    for old in out.glob('org-*.html'):
        if f'profiles/{old.name}' not in current:
            redirect(old.name, {'index.html'})
    return pages


def write_collection_page(title, description, path, article, lead, more, security=False, page_type='CollectionPage', search_title=None):
    """Use the existing static frame for generated evidence and security collections."""
    header, footer = site_frame()
    page = PAGE.format(title=esc(title), site=SITE, desc=esc(description), base=BASE, path=path,
                       img='default', imgalt=DEFAULT_ALT, header=header, footer=footer,
                       lead=lead, article=article, more=more, extra='', h2='',
                       jsonld=profile_jsonld(title, description, path, security=security, page_type=page_type))
    if search_title:
        page = page.replace(f'<title>{esc(title)} · {SITE}</title>',
                            f'<title>{esc(search_title)} · {SITE}</title>', 1)
    (ROOT / path).parent.mkdir(exist_ok=True)
    (ROOT / path).write_text('\n'.join(line.rstrip() for line in relocate(fit_title(page)).splitlines()) + '\n')


def write_catalog_evidence(items):
    """Reproducible composition analysis; annotations are not inferred evidence grades."""
    groups = []
    sections = []
    for dimension in ('year', 'field'):
        keys = sorted({d['publication_date'][:4] if dimension == 'year' else d['field'] for d in items},
                      reverse=dimension == 'year')
        table = []
        for key in keys:
            rows = [d for d in items if (d['publication_date'][:4] if dimension == 'year' else d['field']) == key]
            annotated = sum(bool(d.get('evidence')) for d in rows)
            checked = sum(d['verification_status'] == 'verified' for d in rows)
            groups.append({'grouping': dimension, 'group': key, 'catalog_entries': len(rows),
                           'evidence_annotated': annotated, 'source_checked': checked})
            path = f'profiles/year-{key}.html' if dimension == 'year' else f'profiles/field-{slug(key)}.html'
            table.append(f'<tr><th scope="row"><a href="{path}">{esc(key)}</a></th>'
                         f'<td>{len(rows)}</td><td>{annotated}</td><td>{checked}</td></tr>')
        sections.append(f'<h2>Catalog coverage by {dimension}</h2><div class="security-table"><table>'
                        f'<caption>Active catalog entries grouped by {dimension}; annotation and source-check counts are separate, overlapping attributes.</caption>'
                        f'<thead><tr><th scope="col">{dimension.title()}</th><th scope="col">Entries</th>'
                        '<th scope="col">Evidence annotated</th><th scope="col">Source checked</th></tr></thead>'
                        f'<tbody>{"".join(table)}</tbody></table></div>')
    annotated = sum(bool(d.get('evidence')) for d in items)
    article = ('<div class="prosa"><h2>What does this catalog cover?</h2>'
               f'<p>Of {len(items)} active entries, {annotated} contain a structured evidence annotation '
               f'and {len(items) - annotated} do not. The tables compare the composition of the current catalog, '
               'rather than the rate of scientific progress.</p>'
               '<p><strong>Counting unit:</strong> one active discovery record. Records can overlap and one record can describe several results. '
               'Archived discoveries, model releases and security cases are excluded. Year means the stored publication year, not the year the entry was added.</p>'
               '<p><strong>Evidence annotated</strong> means a nonempty structured evidence object is present. It does not establish that every annotation field '
               'is populated, peer review, independent replication or clinical benefit. <strong>Source checked</strong> means the catalog stores '
               'a completed source check; it is not independent reproduction. These attributes overlap and must not be added together.</p>'
               '<p><strong>Interpretation:</strong> coverage and annotation effort differ by field and year. Import batches can change historical totals. '
               '<a href="methodology.html#evidence-coverage">Inspect field/year acquisition and source-review gaps</a> for finer collection coverage. '
               'A larger count does not prove a more productive field, faster AI progress, or better scientific evidence. '
               'The latest year may be incomplete.</p></div>' + ''.join(sections) +
               '<div class="prosa"><h2>Reproduce and cite this comparison</h2>'
               '<p><a href="data/catalog-summary.csv">Download these exact table rows as CSV</a>. '
               'Group the <a href="data/discoveries.json">active discovery JSON</a> by publication-date year or field, '
               'count records, count nonempty evidence objects and count verification_status values equal to verified. '
               'Each grouping sums to the active catalog size; do not sum the year and field tables together.</p>'
               '<p>For a stable citation, select a matching archived release from '
               '<a href="https://doi.org/10.5281/zenodo.24217686">Zenodo</a> and record its version. '
               'The current page and downloads change with the catalog. '
               '<a href="antibiotic-dossier.html">Compare four antibiotic studies and their experiments</a> for a source-bounded scientific synthesis.</p></div>')
    (ROOT / 'data').mkdir(exist_ok=True)
    write_csv(ROOT / 'data/catalog-summary.csv', ['grouping', 'group', 'catalog_entries', 'evidence_annotated', 'source_checked'], groups)
    write_collection_page('AI discoveries: catalog coverage and evidence',
                          'Compare AI Science Tracker entries by year and scientific field, with evidence annotation coverage, source-check counts and reproducible CSV data.',
                          'profiles/catalog-evidence.html', article,
                          f'{len(items)} active catalog entries · descriptive coverage, not a census of science',
                          '<a href="dataset.html">Dataset, licenses and citation</a> · <a href="methodology.html">Methodology</a>')


def run_security_evidence(items):
    """Reuse the interactive remediation and severity renderers with their source caveats."""
    source = (ROOT / 'security.html').read_text()
    names = ('esc', 'safeUrl', 'date', 'severities')
    declarations = []
    for name in names:
        match = re.search(r'^const ' + name + r' = .*?;$', source, re.M)
        if not match:
            raise ValueError(f'Missing shared security declaration: {name}')
        declarations.append(match[0])
    for name in ('ratingSeverity', 'severity', 'consequences', 'versionParts', 'versionMatch', 'remediationPanel', 'evidence'):
        match = re.search(r'^function ' + name + r'\(.*?^}', source, re.M | re.S)
        if not match:
            raise ValueError(f'Missing shared security renderer: {name}')
        declarations.append(match[0])
    script = '\n'.join(declarations) + ("\nconst records=JSON.parse(require('fs').readFileSync(0,'utf8'));"
             "process.stdout.write(JSON.stringify(Object.fromEntries(records.map(r=>[r.id,{remediation:remediationPanel(r),severity:evidence(r,true)}]))));")
    result = subprocess.run(['node', '-e', script], input=json.dumps(items), capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def write_security_pages(items):
    """Full source-attributed case pages; security counts remain separate from science."""
    rendered = run_security_evidence(items)
    groups = {}
    for record in sorted(items, key=lambda r: (r['disclosure_date'], r['id']), reverse=True):
        path = f'profiles/security-{quote(record["id"])}.html'
        cves = record['cves']
        search_title = f'{cves[0]} · {record["product"]} · AI attribution' if cves else None
        summary = record['summary']
        if cves:
            summary = f'{cves[0]} in {record["product"]} — {summary}'
        description = describe(summary, lead=f'Source-attributed AI discovery report for {record["product"]}')
        attribution = (f'AI attribution dated {nice_date(record["ai_attribution_date"])}'
                       if record['ai_attribution_date'] else 'AI attribution date not established by the source')
        sources = ''.join(f'<li><a href="{esc(safe_url(record[key]))}" rel="noopener">{label}</a></li>' for key, label in
                          [('source_url', 'Original disclosure'), ('ai_source_url', 'AI attribution'), ('advisory_url', 'Advisory / fix evidence')])
        article = (f'<article class="voce" id="{esc(record["id"])}"><h2>Finding and attribution</h2>'
                   f'<p class="sommario">{esc(record["summary"])}</p>'
                   f'{rendered[record["id"]]["remediation"]}'
                   f'<p><strong>Product:</strong> {esc(record["product"])}. <strong>AI system:</strong> {esc(record["ai_system"])}. '
                   f'<strong>Team / organization:</strong> {esc(record["organization"])}.</p>'
                   f'<p><strong>CVE identifiers:</strong> {esc(", ".join(record["cves"]) or "Not established in the cited evidence")}.</p>'
                   f'<p><strong>AI and human contribution (source account):</strong> {esc(record["ai_role"])}</p>'
                   '<p>Human involvement is only described where the source account establishes it; unknown involvement does not mean none. '
                   'Vendor confirmation of a flaw does not confirm every claim about AI contribution.</p>'
                   f'<p><strong>Discovery context:</strong> {esc(record["classification_note"])}</p>'
                   f'<p><strong>Remediation status:</strong> {esc(record["remediation"])}.</p>'
                   '<p>A source-documented fix does not establish installed patches or current safety. '
                   'Source checking does not independently reproduce the finding or establish observed exploitation.</p>'
                   f'<p>Disclosed {nice_date(record["disclosure_date"])}. {attribution}. '
                   f'Sources checked {nice_date(record["checked_date"])}; these are separate dates, not a live installation check.</p>'
                   f'{rendered[record["id"]]["severity"]}<h2>Original evidence</h2><ul>{sources}</ul>'
                   f'<p><a href="api/v1/vulnerabilities/{quote(record["id"])}.json">Download this source record (JSON)</a></p></article>')
        write_collection_page(record['title'], description, path, article,
                              f'{esc(record["product"])} · AI involvement attributed to {esc(record["ai_system"])}',
                              f'<a href="security.html#{quote(record["id"])}">Open this case in the interactive tracker</a> · '
                              '<a href="profiles/security-index.html">Browse all static security cases</a>',
                              security=True, page_type='WebPage', search_title=search_title)
        groups.setdefault(record['disclosure_date'][:4], []).append(record)
    listings = ''.join(f'<h2>Disclosures in {year}</h2><ul class="elenco-profili">' + ''.join(
        f'<li><a href="profiles/security-{quote(r["id"])}.html">{esc(r["title"])}</a> · '
        f'{esc(", ".join(r["cves"]) or r["product"])}</li>' for r in rows) + '</ul>' for year, rows in groups.items())
    article = ('<div class="prosa"><h2>Read the source-attributed evidence</h2><p>Each case preserves the original finding, '
               'AI and human contribution, separate disclosure and attribution dates, reported severity assessments and remediation limits. '
               'These cases are separate from scientific-discovery counts. Missing evidence does not establish absence of exploitation.</p></div>' + listings)
    write_collection_page('Vulnerabilities found by AI: source-linked cases',
                          'Browse publicly disclosed AI-found vulnerability cases, CVEs, original disclosures, AI attribution and documented remediation caveats without JavaScript.',
                          'profiles/security-index.html', article, f'{len(items)} cases · selected public evidence, not a complete vulnerability inventory',
                          '<a href="security.html">Interactive filters and charts</a> · <a href="dataset.html">Download security data</a>', security=True)


def write_llms_txt(items, models):
    """llms.txt: a plain summary for language-model crawlers. Counts come from the data so it never goes stale."""
    fields = len({d['field'] for d in items})
    orgs = len({lead_org(d['organization']) for d in items if canonical_organization(d['organization'])['kind'] != 'unknown affiliation'})
    newest = max(d['added_date'] for d in items)
    insights_line = f'- [Insights]({BASE}insights.html): the whole catalog in plain-language charts\n' if (ROOT / 'insights.html').is_file() else ''
    (ROOT / 'llms.txt').write_text(f'''# {SITE}

> A catalog of {len(items)} entries about scientific results enabled by AI across {fields} fields and {orgs} organizations since 2020. Each entry links to an original paper, preprint or institutional announcement. Entry counts are not counts of independent findings: methodological contributions can overlap other entries, and one entry can describe several related results. Figures are reported by the sources and are not independently verified; relevance scores are coarse editorial judgments, not evidence grades.

Content is licensed CC BY 4.0 (attribute "{SITE}" with a link); site code is MIT. Epoch AI model data is CC BY 4.0. The separate SWE-bench selection (data/swe-bench.json) is CC BY-NC 4.0, for noncommercial reuse only; it is not covered by the catalog CC BY 4.0 grant. Additional numerical benchmarks (data/benchmarks/) retain per-component CC BY 4.0, CC BY-SA 4.0, MIT or Apache-2.0 terms; see docs/public-benchmarks.md. CharXiv adapted data is CC BY-SA 4.0. These components are excluded from the blanket catalog license and catalog Hugging Face export. When citing a scientific claim, cite the original source linked on each entry, not this catalog.

## Browse
- [Discoveries]({BASE}): filters, charts and the full list
- [Organizations and model families]({BASE}profiles/index.html): static profile pages
- [Model progress]({BASE}model-progress.html): exact model comparison, ECI, benchmark evidence and recorded release rhythm
- [Search all collections]({BASE}search.html): literal retrieval with separate counts and match reasons
{insights_line}- [Evidence dossiers]({BASE}dossiers.html): selected studies and public vulnerability disclosures with evidence limits
- [Antibiotic evidence dossier]({BASE}antibiotic-dossier.html): dated, source-bounded synthesis
- [Catalog coverage and evidence]({BASE}profiles/catalog-evidence.html): reproducible composition tables, counting limits and CSV
- [Static AI-found security cases]({BASE}profiles/security-index.html): source-attributed case pages readable without JavaScript
- [Models]({BASE}models.html): model releases linked to discoveries
- [Vuln discoveries]({BASE}security.html): publicly disclosed vulnerabilities with documented AI involvement, kept separate from the scientific count
- [Methodology]({BASE}methodology.html): what is included, how entries are verified and scored

## Data
- [discoveries.json]({BASE}data/discoveries.json): active catalog entries (schema and counting unit: docs/discovery-schema.md in the repository)
- [models.json]({BASE}data/models.json): model releases and families
- [model-progress.json]({BASE}data/model-progress.json): separate Epoch capability/benchmark source entries; may overlap releases
- [Independent benchmark directory]({BASE}data/benchmarks/index.json): 11 separately licensed numerical snapshots; source-specific selections and limits
- [vulnerabilities.json]({BASE}data/vulnerabilities.json): vulnerability cases
- [sitemap.xml]({BASE}sitemap.xml): every static page
- [dataset.html]({BASE}dataset.html): downloads (JSON, CSV), schemas and the read-only static API at {BASE}api/v1/index.json
- [contributors.html]({BASE}contributors.html): maintainer, contributors and how to contribute
- [feed.xml]({BASE}feed.xml): Atom feed of discovery additions and vulnerability source checks
- Each discovery has its own page at {BASE}share/ID.html
- [llms-full.txt]({BASE}llms-full.txt): every entry as plain text (title, date, field, organization, summary, source)

## For agents
- MCP server (Streamable HTTP, read-only, no token): https://mcp.aisciencetracker.org/mcp with tools search_discoveries, get_discovery, list_fields, search_vulnerabilities and get_vulnerability; Server Card at https://mcp.aisciencetracker.org/mcp/server-card, AI Catalog at {BASE}.well-known/ai-catalog.json
- [OpenAPI description]({BASE}api/v1/openapi.json) of the static JSON API

## Notes
- Most recent catalog addition: {newest}. This is not a last-review date.
- The collection is manual and not exhaustive; most sources are the announcing organizations' own pages.
- Repository: https://github.com/marcello-pichini/ai-science-tracker
''')
    # AI Catalog (MCP Server Cards, SEP-2127) for domain-level discovery of the MCP server.
    (ROOT / '.well-known').mkdir(exist_ok=True)
    (ROOT / '.well-known/ai-catalog.json').write_text(json.dumps({'specVersion': '1.0', 'entries': [{
        'identifier': 'urn:air:aisciencetracker.org:mcp:ai-science-tracker', 'type': 'application/mcp-server-card+json',
        'url': 'https://mcp.aisciencetracker.org/mcp/server-card'}]}, indent=2) + '\n')
    entries = ''.join(
        f"\n## {d['title'].strip()}\n{d['publication_date']} · {d['field']} · {d['organization'].strip()}\n"
        f"Page: {BASE}share/{quote(d['id'])}.html\nSource: {d['source_url']}\n\n{d['summary'].strip()}\n"
        for d in sorted(items, key=lambda d: (d['publication_date'], d['id']), reverse=True))
    (ROOT / 'llms-full.txt').write_text(
        f'# {SITE}: full catalog\n\n> All {len(items)} active entries, newest first. Figures are reported by the sources '
        'and are not independently verified; cite the linked original source, not this catalog. '
        f'Licensed CC BY 4.0 (attribute "{SITE}" with a link). Structured data: {BASE}data/discoveries.json\n' + entries)


def write_sitemap(items, models, archived=(), vulns=()):
    org_counts = Counter(lead_org(d['organization']) for d in items)
    orgs = sorted(o for o, n in org_counts.items() if n >= ORG_INDEX_MIN)
    fams = sorted(f['id'] for f in models['families'] if f['discoveries'])
    # Announcement and catalog-addition dates are not page-modification dates. lastmod is the date the
    # generator first saw the page's current substantive content (snapshot hashes and counts ignored),
    # kept in data/page-lastmod.json; dossiers with an explicit editorial update date use that date.
    # search.html is a translated editorial page. profile.html and 404.html are noindex.
    # Localized copies exist only for translated editorial pages, not for share/ or profiles/.
    urls = ['index.html', 'models.html', 'methodology.html', 'guide.html', 'security.html', 'search.html', 'dataset.html', 'contributors.html', 'contact.html', 'model-progress.html', 'dossiers.html', 'alphafold-dossier.html', 'antibiotic-dossier.html']
    from i18n_site import LOCALES, NEW_DOSSIER_PAGES, SITEMAP_PAGES, dossier_modified_date, public_url

    urls.extend(NEW_DOSSIER_PAGES)
    if (ROOT / 'insights.html').is_file():
        urls.append('insights.html')
    urls += ['profiles/index.html']
    urls += ['profiles/catalog-evidence.html', 'profiles/security-index.html']
    urls += [f'profiles/security-{quote(v["id"])}.html' for v in vulns]
    urls += [f'profiles/org-{slug(o)}.html' for o in orgs]
    urls += [f'profiles/family-{quote(f)}.html' for f in fams]
    urls += [f'profiles/field-{slug(f)}.html' for f in sorted({d['field'] for d in items})]
    urls += [f'profiles/year-{y}.html' for y in sorted({d['publication_date'][:4] for d in items}, reverse=True)]
    urls += [f'share/{quote(d["id"])}.html' for d in [*items, *archived]]

    def alternates(page):
        links = [f'<xhtml:link rel="alternate" hreflang="en" href="{esc(public_url(page, "en"))}"/>']
        links += [f'<xhtml:link rel="alternate" hreflang="{code}" href="{esc(public_url(page, code))}"/>' for code in LOCALES]
        links.append(f'<xhtml:link rel="alternate" hreflang="x-default" href="{esc(public_url(page, "en"))}"/>')
        return ''.join(links)

    from indexnow import substantive
    state_path = ROOT / 'data/page-lastmod.json'
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    dates = {}
    rows = []
    seen = set()
    for url in urls:
        block = alternates(url) if url in SITEMAP_PAGES else ''
        lastmod = ''
        if (ROOT / url).is_file():
            text = (ROOT / url).read_text(encoding='utf-8')
            digest = hashlib.sha256(substantive(text).encode()).hexdigest()[:16]
            known = state.get(url, '').split(' ')
            dates[url] = f'{digest} {known[1] if known[0] == digest and len(known) == 2 else today}'
            updated = dossier_modified_date(text) if url.endswith('-dossier.html') else None
            lastmod = f'<lastmod>{updated or dates[url].split(" ")[1]}</lastmod>'
        targets = [public_url(url, 'en')] if url in SITEMAP_PAGES else [BASE + url]
        if url in SITEMAP_PAGES:
            targets += [public_url(url, code) for code in LOCALES]
        for loc in targets:
            if loc in seen or loc.endswith('/index.html'):
                continue
            seen.add(loc)
            rows.append(f'<url><loc>{esc(loc)}</loc>{lastmod}{block}</url>\n')
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text(json.dumps(dates, indent=0, sort_keys=True) + '\n')
    (ROOT / 'sitemap.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        + ''.join(rows) + '</urlset>\n')
    # AI crawlers are already allowed by '*'; naming them states the intent explicitly.
    ai_bots = ('GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'ClaudeBot', 'Claude-SearchBot', 'Claude-User',
               'PerplexityBot', 'Perplexity-User', 'Google-Extended', 'Applebot-Extended', 'CCBot', 'meta-externalagent')
    named = ''.join(f'User-agent: {b}\n' for b in ai_bots)
    (ROOT / 'robots.txt').write_text(f'User-agent: *\nAllow: /\n\n{named}Allow: /\n\nSitemap: {BASE}sitemap.xml\n')


def write_feed(items, vulns, limit=40):
    """Order discoveries by addition date and vulnerabilities by source-check date."""
    rows = []
    for d in items:
        path = f'share/{quote(d["id"])}.html'
        rows.append((d['added_date'], d['publication_date'], path, path, d['title'], d['summary'],
                     f'Discovery - {d["organization"]}'))
    for v in vulns:
        path = f'profiles/security-{quote(v["id"])}.html'
        rows.append((v['checked_date'], v['disclosure_date'], f'security.html#{quote(v["id"])}', path, v['title'], v['summary'],
                     f'Vulnerability - {v["organization"]}'))
    rows = sorted(rows, reverse=True)[:limit]
    entries = ''.join(
        f'<entry><id>{esc(BASE + entry_id)}</id><title>{esc(title)}</title><link href="{esc(BASE + path)}"/>'
        f'<updated>{added}T00:00:00Z</updated><category term="{esc(cat.split(" - ")[0].lower())}"/>'
        f'<summary>{esc(clip(summary, 300))} ({esc(cat)}; announced {announced})</summary></entry>\n'
        for added, announced, entry_id, path, title, summary, cat in rows)
    (ROOT / 'feed.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f'<id>{BASE}feed.xml</id><title>{SITE}: additions and source checks</title>'
        f'<link rel="self" href="{BASE}feed.xml"/><link href="{BASE}"/>'
        f'<updated>{rows[0][0]}T00:00:00Z</updated><author><name>{SITE}</name></author>\n{entries}</feed>\n')


CSV_DISCOVERY = ['id', 'title', 'summary', 'field', 'ai_technology', 'organization', 'source_url', 'source_type', 'publication_date',
                 'added_date', 'verification_status', 'paper_url', 'impact', 'validation', 'novelty', 'catalog_entry_url', 'publication_status', 'test_type', 'tested', 'unknown', 'ai_role', 'evidence_urls', 'source_review', 'follow_up', 'follow_up_review', 'relationships']
CSV_VULN = ['id', 'title', 'product', 'ai_system', 'organization', 'disclosure_date', 'classification', 'cves', 'source_url',
            'ai_source_url', 'advisory_url', 'remediation', 'checked_date', 'summary', 'ai_role',
            'ai_attribution_date', 'classification_note', 'remediation_note', 'cvss', 'impacts', 'remediation_details']


def write_csv(path, columns, rows):
    with (ROOT / path).open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(columns)
        for row in rows:
            cells = [str(row[c]) if row[c] is not None else '' for c in columns]
            w.writerow(["'" + cell if cell.startswith(('=', '+', '-', '@', '\t', '\r')) else cell for cell in cells])


def write_exports(items, vulns):
    """Flat CSV copies of the JSON data, same columns as the in-page download. Evidence and optional histories retain their fields; nested structures are JSON cells."""
    write_csv('data/discoveries.csv', CSV_DISCOVERY, [
        dict(d, **d['relevance'], **{key: d.get('evidence', {}).get(key, '') for key in ('publication_status', 'test_type', 'tested', 'unknown', 'ai_role')}, evidence_urls=json.dumps(d.get('evidence', {}).get('evidence_urls', []), ensure_ascii=False, separators=(',', ':')), **{key: json.dumps(d.get(key), ensure_ascii=False, separators=(',', ':')) for key in ('source_review', 'follow_up', 'follow_up_review', 'relationships')}, catalog_entry_url=f'{BASE}share/{d["id"]}.html') for d in items])
    write_csv('data/vulnerabilities.csv', CSV_VULN, [
        dict(v, cves=';'.join(v['cves']), remediation_details=json.dumps(v['remediation_details'], ensure_ascii=False, separators=(',', ':')) if 'remediation_details' in v else '',
             **{key: json.dumps(v.get(key, []), ensure_ascii=False, separators=(',', ':')) for key in ('cvss', 'impacts')})
        for v in vulns])


def write_api(items, vulns, models=None, archived=(), manifest=None):
    """Read-only static API: api/v1/index.json plus one JSON file per record. The full lists stay in data/*.json."""
    for kind, rows in (('discoveries', items), ('vulnerabilities', vulns)):
        out = ROOT / 'api/v1' / kind
        out.mkdir(parents=True, exist_ok=True)
        for r in rows:
            (out / f'{r["id"]}.json').write_text(json.dumps(r, indent=2, ensure_ascii=False) + '\n')
        current = {f'{r["id"]}.json' for r in rows}
        for old in out.glob('*.json'):
            if old.name not in current:
                old.unlink()
    api = BASE + 'api/v1/'
    index = {
        'name': SITE, 'api_version': 'v1', 'license': 'CC BY 4.0 (catalog content); Epoch AI model data keeps its own CC BY 4.0 attribution',
        'license_url': 'https://creativecommons.org/licenses/by/4.0/', 'cite': 'https://doi.org/10.5281/zenodo.24217686',
        'data_version_date': max(d['added_date'] for d in items),  # Legacy alias for latest_discovery_addition_date.
        'latest_discovery_addition_date': max(d['added_date'] for d in items),
        'catalog_sha256': hashlib.sha256(json.dumps([items, vulns, models, list(archived)], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest(),
        'counts': {'discoveries': len(items), 'vulnerabilities': len(vulns)},
        'endpoints': {
            'discoveries_list': BASE + 'data/discoveries.json', 'discovery': api + 'discoveries/{id}.json',
            'vulnerabilities_list': BASE + 'data/vulnerabilities.json', 'vulnerability': api + 'vulnerabilities/{id}.json',
            'models_list': BASE + 'data/models.json', 'model_progress': BASE + 'data/model-progress.json'},
        'downloads': {'discoveries_csv': BASE + 'data/discoveries.csv', 'vulnerabilities_csv': BASE + 'data/vulnerabilities.csv'},
        'schemas': {'discoveries': BASE + 'schema/discoveries.schema.json', 'vulnerabilities': BASE + 'schema/vulnerabilities.schema.json'},
        'documentation': BASE + 'dataset.html', 'openapi': api + 'openapi.json'}
    write_openapi(len(items), len(vulns))
    if manifest is not None:
        index['component_manifest'] = BASE + 'api/v1/manifest.json'
        index['snapshot_sha256'] = manifest['snapshot_sha256']
    (ROOT / 'api/v1/index.json').write_text(json.dumps(index, indent=2) + '\n')



def write_openapi(discoveries, vulnerabilities):
    """OpenAPI 3.1 description of the static, read-only JSON files, so agents and tools can call them unaided."""
    def get(summary, schema, by_id=False):
        op = {'summary': summary, 'responses': {'200': {'description': 'JSON document', 'content': {'application/json': {'schema': schema}}}}}
        if by_id:
            op['responses']['404'] = {'description': 'No record with this ID'}
            op['parameters'] = [{'name': 'id', 'in': 'path', 'required': True, 'description': 'Stable record ID',
                                 'schema': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9-]*$'}}]
        return {'get': op}
    spec = {
        'openapi': '3.1.0',
        'info': {'title': f'{SITE} static API', 'version': 'v1',
                 'description': f'Read-only JSON files: {discoveries} AI-enabled scientific discoveries and {vulnerabilities} '
                                'AI-found vulnerability cases. No authentication. Figures are reported by the linked sources; '
                                'cite the original source of a claim.',
                 'license': {'name': 'CC BY 4.0', 'url': 'https://creativecommons.org/licenses/by/4.0/'}},
        'servers': [{'url': BASE.rstrip('/')}],
        'externalDocs': {'url': BASE + 'dataset.html'},
        'paths': {
            '/api/v1/index.json': get('API index with counts, endpoints and checksums', {'type': 'object'}),
            '/data/discoveries.json': get('Every active discovery', {'$ref': f'{BASE}schema/discoveries.schema.json'}),
            '/api/v1/discoveries/{id}.json': get('One discovery', {'$ref': f'{BASE}schema/discoveries.schema.json#/items'}, True),
            '/data/vulnerabilities.json': get('Every AI-found vulnerability case', {'$ref': f'{BASE}schema/vulnerabilities.schema.json'}),
            '/api/v1/vulnerabilities/{id}.json': get('One vulnerability case', {'$ref': f'{BASE}schema/vulnerabilities.schema.json#/items'}, True),
        },
    }
    (ROOT / 'api/v1/openapi.json').write_text(json.dumps(spec, indent=2) + '\n')


def validate_discovery_context(records):
    """Optional annotations require provenance; missing review history remains unknown."""
    ids = {record['id'] for record in records}
    def text(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Context text must be nonempty')
    def date(value):
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Review and recording dates require day precision')
        datetime.date.fromisoformat(value)
    def sources(value):
        if not isinstance(value, list) or not value or any(not isinstance(url, str) or not re.fullmatch(r'https://[^/\s?#]+(?:[/?#]\S*)?', url) for url in value):
            raise ValueError('Context annotations need HTTPS sources')
    for record in records:
        for key in ('source_review', 'follow_up_review'):
            if key in record:
                date(record[key]['date'])
                text(record[key]['scope'])
        events = record.get('follow_up', [])
        if not isinstance(events, list) or len({event['id'] for event in events}) != len(events):
            raise ValueError('Follow-up IDs must be unique within an entry')
        for event in events:
            if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', event['id']):
                raise ValueError('Follow-up IDs must be safe slugs')
            if event['kind'] not in ('publication', 'same-team extension', 'independent follow-up', 'documented application', 'contradiction', 'correction', 'retraction'):
                raise ValueError('Unknown follow-up kind')
            precision, value = event['date_precision'], event['date']
            patterns = {'year': r'\d{4}', 'month': r'\d{4}-\d{2}', 'day': r'\d{4}-\d{2}-\d{2}'}
            if precision == 'unknown':
                if value is not None:
                    raise ValueError('Unknown follow-up date must be null')
            elif precision not in patterns or not isinstance(value, str) or not re.fullmatch(patterns[precision], value):
                raise ValueError('Follow-up date must match its precision')
            else:
                datetime.date.fromisoformat(value + ('-01-01' if precision == 'year' else '-01' if precision == 'month' else ''))
            text(event['note'])
            sources(event['source_urls'])
            date(event['recorded_date'])
        links = record.get('relationships', [])
        if not isinstance(links, list):
            raise ValueError('Relationships must be an array')
        seen = set()
        for link in links:
            pair = (link['type'], link['target_id'])
            if link['type'] not in ('same result', 'extends', 'independent follow-up', 'shared evidence') or link['target_id'] not in ids or link['target_id'] == record['id'] or pair in seen:
                raise ValueError('Invalid or duplicate directed relationship')
            seen.add(pair)
            text(link['reason'])
            sources(link['source_urls'])


def validate_inputs(items, archived, models, vulns):
    validate_discovery_context(items + archived)
    if not items:
        raise ValueError('At least one active discovery is required')
    for rows in (items + archived, vulns):
        ids = [r['id'] for r in rows]
        if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value) for value in ids):
            raise ValueError('Record IDs must be unique safe slugs')
    for d in items + archived:
        for key in ('id', 'title', 'summary', 'field', 'ai_technology', 'organization', 'source_url', 'source_type', 'publication_date', 'added_date', 'verification_status', 'paper_url'):
            d[key]
        for key in ('impact', 'validation', 'novelty'):
            d['relevance'][key]
        for key in ('publication_date', 'added_date'):
            datetime.date.fromisoformat(d[key])
    for v in vulns:
        for key in CSV_VULN:
            if key not in ('cvss', 'impacts', 'remediation_details'):
                v[key]
        cves = set(v['cves'])
        if any(rating['cve'] is not None and rating['cve'] not in cves for rating in v.get('cvss', [])) or any(not set(impact['cves']) <= cves for impact in v.get('impacts', [])):
            raise ValueError('Vulnerability evidence CVEs must belong to the case')
        for key in ('disclosure_date', 'ai_attribution_date', 'checked_date'):
            if key == 'ai_attribution_date' and v[key] is None:
                continue
            datetime.date.fromisoformat(v[key])
        if 'remediation_details' in v:
            detail = v['remediation_details']
            if not str(detail['source_url']).startswith('https://'):
                raise ValueError('Remediation details require an HTTPS source')
            datetime.date.fromisoformat(detail['checked_date'])
            if 'comparison' in detail:
                comparison = detail['comparison']
                if not re.fullmatch(r'\d{1,8}\.\d{1,8}\.\d{1,8}', comparison['upper_bound']) or not isinstance(comparison['inclusive'], bool):
                    raise ValueError('Remediation comparison requires an explicit three-part upper bound and inclusivity')
    models['families']
    models['models']


BROWSE_START, BROWSE_END = '<!-- browse:start -->', '<!-- browse:end -->'
PULSE_START, PULSE_END = '<!-- pulse:start -->', '<!-- pulse:end -->'
PLAIN_START, PLAIN_END = '<!-- plain:start -->', '<!-- plain:end -->'


def hero_pulse_html(items):
    """Static homepage panel: publication-year counts and the latest catalog additions.

    Built from the discovery records at generation time. No client request and no library.
    Titles stay inside data-i18n-skip so a new entry does not create a translation key;
    the page script localizes the date and the field name when messages are available.
    """
    counts = Counter(d['publication_date'][:4] for d in items)
    years = sorted(counts)
    if not years:
        return f'{PULSE_START}\n{PULSE_END}'
    latest = sorted(items, key=lambda d: (d.get('added_date') or d['publication_date'], d['publication_date'], d['id']), reverse=True)[:4]
    width, height, gap = 320, 156, 8
    top, bottom = 22, 22
    plot = height - top - bottom
    bar_w = (width - gap * (len(years) - 1)) / len(years)
    peak = max(counts.values())
    current = str(datetime.date.today().year)
    parts = []
    for i, year in enumerate(years):
        count = counts[year]
        bar_h = max(3, round(count / peak * plot, 2))
        x = round(i * (bar_w + gap), 2)
        y = round(top + plot - bar_h, 2)
        bw = round(bar_w, 2)
        klass = 'hero-bar hero-bar-now' if year == current else 'hero-bar'
        delay = i * 40
        parts.append(
            f'<a href="./?year={year}#elenco" aria-label="{esc(f"{year}: {count} catalog entries")}">'
            f'<rect class="{klass}" style="--d:{delay}ms" x="{x}" y="{y}" width="{bw}" height="{bar_h}" rx="3"/>'
            f'<text class="hero-count" x="{round(x + bw / 2, 2)}" y="{max(11, round(y - 4, 2))}" text-anchor="middle">{count}</text>'
            f'<text class="hero-year" x="{round(x + bw / 2, 2)}" y="{height - 4}" text-anchor="middle">{year}</text></a>'
        )
    rows = ''.join(
        f'<tr><td>{esc(year)}</td><td>{counts[year]}</td></tr>' for year in years)
    entries = ''.join(
        '<li><a href="share/{id}.html">{title}</a>'
        '<p class="hero-meta"><time datetime="{added}">{shown}</time>'
        '<span class="hero-field">{field}</span></p></li>'.format(
            id=esc(d['id']), title=esc(d['title']),
            added=esc(d.get('added_date') or d['publication_date']),
            shown=esc(nice_date(d.get('added_date') or d['publication_date'])),
            field=esc(d['field']))
        for d in latest)
    caption = ('Catalog entries by publication year. Bar height is the number of entries in this collection, '
               'not a measure of scientific quality.')
    if years[-1] == current:
        caption += ' The latest year is still in progress.'
    figure = (
        '<figure class="hero-chart">'
        f'<svg viewBox="0 0 {width} {height}" role="group" aria-labelledby="hero-chart-cap">{"".join(parts)}</svg>'
        f'<figcaption id="hero-chart-cap">{caption}</figcaption>'
        '<details><summary>View data as a table</summary>'
        '<table class="tab-mini"><caption class="vis-nascosto">Catalog entries by publication year</caption>'
        '<thead><tr><th>Year</th><th>Catalog entries</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></details></figure>'
    )
    return (
        f'{PULSE_START}\n'
        '<aside class="hero-live" aria-labelledby="hero-live-title">'
        '<h2 id="hero-live-title">Recently added</h2>'
        '<p class="hero-kicker">Four entries most recently added to this catalog, and how many entries each publication year holds.</p>'
        f'<ol class="hero-latest" data-i18n-skip>{entries}</ol>'
        f'{figure}</aside>\n'
        f'{PULSE_END}'
    )


def write_hero_pulse(items):
    path = ROOT / 'index.html'
    page = path.read_text()
    if PULSE_START not in page or PULSE_END not in page:
        return
    start, end = page.index(PULSE_START), page.index(PULSE_END) + len(PULSE_END)
    path.write_text(page[:start] + hero_pulse_html(items) + page[end:])


PLAIN_LIMITS = {'headline': 90, 'plain': 240, 'why': 180, 'unknown': 180}
TESTED_NOTE = ('The level reflects the test the original source reports. This site does not rerun it, '
               'and it does not say whether the result is correct.')


def load_plain():
    """data/plain-language.json, or an empty layer when the file does not exist."""
    path = ROOT / 'data/plain-language.json'
    if not path.is_file():
        return {'home': [], 'landmarks': [], 'records': {}}
    return json.loads(path.read_text())


def plain_source(d):
    """Fingerprint of the discovery fields the plain-language texts were written from."""
    ev = d.get('evidence') or {}
    parts = [d.get('title') or '', d.get('summary') or '', ev.get('tested') or '', ev.get('unknown') or '',
             ev.get('test_type') or '']
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode('utf-8')).hexdigest()[:12]


def validate_plain(plain):
    """Fail before any output is written when the layer is structurally broken (only a human edit can do that)."""
    for key in ('home', 'landmarks'):
        if not isinstance(plain.get(key, []), list) or not all(isinstance(i, str) for i in plain.get(key, [])):
            raise ValueError(f'plain-language.json {key}: must be a list of ids')
    for did, rec in plain.get('records', {}).items():
        if not isinstance(rec, dict) or set(rec) != set(PLAIN_LIMITS) | {'source'}:
            raise ValueError(f'plain-language.json {did}: needs exactly the fields {sorted(set(PLAIN_LIMITS) | {"source"})}')
        for field in list(PLAIN_LIMITS) + ['source']:
            if not isinstance(rec[field], str):
                raise ValueError(f'plain-language.json {did}.{field}: must be a string')
        for field, limit in PLAIN_LIMITS.items():
            if len(rec[field]) > limit:
                raise ValueError(f'plain-language.json {did}.{field}: {len(rec[field])} characters, limit {limit}')


def usable_plain(plain, items):
    """The layer for this catalog: records for retired ids or written from an older version of the record are dropped with a warning."""
    by_id = {d['id']: d for d in items}
    records = {}
    for did, rec in plain.get('records', {}).items():
        if did not in by_id:
            print(f'warning: plain-language.json {did}: not an active discovery, skipped', file=sys.stderr)
        elif rec['source'] != plain_source(by_id[did]):
            print(f'warning: plain-language.json {did}: the discovery record changed since the text was reviewed, skipped',
                  file=sys.stderr)
        else:
            records[did] = rec
    return dict(plain, records=records, home=[i for i in plain.get('home', []) if i in records],
                landmarks=[i for i in plain.get('landmarks', []) if i in records])


def stamp_plain(items):
    """Rewrite only the source fingerprints in data/plain-language.json, after a human re-reviewed the texts."""
    path = ROOT / 'data/plain-language.json'
    plain = json.loads(path.read_text())
    by_id = {d['id']: d for d in items}
    for did, rec in plain.get('records', {}).items():
        if did in by_id:
            rec['source'] = plain_source(by_id[did])
    path.write_text(json.dumps(plain, ensure_ascii=False, indent=2) + '\n')


def plain_text(plain, did):
    return (plain.get('records', {}).get(did) or {}).get('plain', '').strip()


def plain_share_links(d):
    """Plain links, no JavaScript: X, LinkedIn and the existing preview card."""
    url = f'{BASE}share/{d["id"]}.html'
    x = f'https://x.com/intent/post?text={quote(d["title"], safe="")}&url={quote(url, safe="")}'
    li = f'https://www.linkedin.com/sharing/share-offsite/?url={quote(url, safe="")}'
    return [f'<a href="{esc(x)}" target="_blank" rel="noopener">Share on X</a>',
            f'<a href="{esc(li)}" target="_blank" rel="noopener">Share on LinkedIn</a>']


def plain_short_version(d, plain, has_image):
    """The plain-language block above a discovery page's record content."""
    rec = plain.get('records', {}).get(d['id']) or {}
    text = rec.get('plain', '').strip()
    cells = []
    if text:
        cells.append(('In plain words', text))
        cells.append(('Why it matters', rec.get('why', '').strip()))
    def cell(head, body):
        return f'<div><h3>{esc(head)}</h3><p>{esc(body)}</p></div>' if body else ''
    top = ''.join(cell(*c) for c in cells)
    meter = f'<p>{evidence_levels.meter_html(d)}</p><p class="plain-note">{esc(TESTED_NOTE)}</p>'
    tested = f'<div><h3>{esc(evidence_levels.HEADING)}</h3>{meter}</div>' if text else f'<div>{meter}</div>'
    unknown = cell('What we still do not know', rec.get('unknown', '').strip()) if text else ''
    links = plain_share_links(d)
    if has_image:
        links.append(f'<a href="og/{quote(d["id"])}.png" download>Download image</a>')
    share = ('<ul class="plain-share" aria-label="Share this discovery">'
             + ''.join(f'<li>{a}</li>' for a in links) + '</ul>')
    grid = f'<div class="plain-grid">{top}</div>' if top else ''
    heading = 'The short version' if text else evidence_levels.HEADING
    return (f'<section class="plain-short" aria-labelledby="plain-short-h"><h2 id="plain-short-h">{esc(heading)}</h2>'
            f'{grid}<div class="plain-grid">{tested}{unknown}</div>{share}</section>')


def plain_home_html(items, plain):
    """Start-here cards for the home page: one per complete id in plain["home"]."""
    by_id = {d['id']: d for d in items}
    cards = []
    for did in plain.get('home', []):
        rec = plain.get('records', {}).get(did) or {}
        if did not in by_id or not rec.get('headline', '').strip() or not rec.get('plain', '').strip():
            continue
        d = by_id[did]
        cards.append(
            f'<article class="plain-card"><div class="plain-meta"><span class="etich" data-i18n>{esc(d["field"])}</span>'
            f'<time datetime="{esc(d["publication_date"][:4])}">{esc(d["publication_date"][:4])}</time></div>'
            f'<h3><a href="share/{esc(did)}.html"><span data-i18n>{esc(rec["headline"])}</span></a></h3>'
            f'<p>{esc(rec["plain"])}</p><p class="plain-level">{evidence_levels.meter_html(d)}</p></article>')
    if not cards:
        return f'{PLAIN_START}\n{PLAIN_END}'
    return (f'{PLAIN_START}\n<p class="plain-kicker">Start here</p>\n<div class="plain-cards">{"".join(cards)}</div>\n'
            '<p class="plain-more"><a href="insights.html">See the whole catalog in charts</a></p>\n'
            f'{PLAIN_END}')


def write_plain_home(items, plain):
    path = ROOT / 'index.html'
    page = path.read_text()
    if PLAIN_START not in page or PLAIN_END not in page:
        return
    start, end = page.index(PLAIN_START), page.index(PLAIN_END) + len(PLAIN_END)
    path.write_text(page[:start] + plain_home_html(items, plain) + page[end:])


def write_page_summaries(items, models):
    summaries = {
        'index.html': (f'<b>{len(items)} discoveries</b> in {len({d["field"] for d in items})} fields and '
                       f'{len({lead_org(d["organization"]) for d in items if canonical_organization(d["organization"])["kind"] != "unknown affiliation"})} organizations since 2020. '
                       'Browse source-linked findings below.'),
        'models.html': (f'<b>{len(models["models"])} selected releases</b> from Epoch AI, including leading labs since 2020 and tracked families from any date. '
                        f'<b>{sum(f.get("discovery_count", 0) > 0 for f in models["families"])} families</b> of models are matched by name '
                        f'to at least one of {len(items)} catalog discoveries, covering {len(models.get("linked_discoveries", []))} discoveries in total.')}
    for name, summary in summaries.items():
        path = ROOT / name
        if path.exists():
            path.write_text(re.sub(r'(<p class="lead" id="lead">).*?(</p>)',
                                   lambda m: m[1] + summary + m[2], path.read_text(), flags=re.S))

    progress_page = ROOT / 'model-progress.html'
    if progress_page.exists():
        progress = json.loads((ROOT / 'data/model-progress.json').read_text())
        retrieved = nice_date(progress['fetched_on'])
        progress_page.write_text(re.sub(r'(<span id="(?:import-date|cadence-period)">)[^<]*(</span>)',
                                        lambda m: m[1] + retrieved + m[2], progress_page.read_text()))

def write_home_browse(items, latest=50):
    """Write plain links into index.html: every year page (which links each of its entries) and the
    newest entries, so search engines and readers without JavaScript reach every entry within two
    steps without a 1 MB home page."""
    path = ROOT / 'index.html'
    page = path.read_text()
    if BROWSE_START not in page:
        return
    rows = sorted(items, key=lambda d: d['publication_date'], reverse=True)
    years = Counter(d['publication_date'][:4] for d in rows)
    fields = ' · '.join(f'<a href="profiles/field-{slug(f)}.html">{esc(f)}</a>' for f in sorted({d['field'] for d in items}))
    by_year = ' · '.join(f'<a href="profiles/year-{y}.html">{y} ({n})</a>' for y, n in sorted(years.items(), reverse=True))
    newest = ''.join(f'<li><a href="share/{esc(d["id"])}.html">{esc(d["title"])}</a></li>' for d in rows[:latest])
    section = (f'{BROWSE_START}\n  <section class="sez" aria-labelledby="t-browse"><div class="wrap prosa">\n'
               f'    <h2 id="t-browse">All entries by year</h2>\n'
               f'    <p>Each year page links every one of its entries; {len(items)} in total.</p>\n'
               f'    <h3>By year</h3><p>{by_year}</p>\n'
               f'    <p>By field: {fields}.</p>\n'
               '    <p><a href="profiles/catalog-evidence.html">Compare catalog coverage and evidence by year and field</a> · '
               '<a href="profiles/security-index.html">Browse source-linked AI-found vulnerability cases</a>.</p>\n'
               f'    <h3>Newest {min(latest, len(rows))} entries</h3><ul>{newest}</ul>\n'
               f'  </div></section>\n  {BROWSE_END}')
    start, end = page.index(BROWSE_START), page.index(BROWSE_END) + len(BROWSE_END)
    path.write_text(page[:start] + section + page[end:])


def main():
    from i18n_site import install_english_chrome, write_locale_pages
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-images', action='store_true', help='Skip PNG rendering; reuse existing per-entry images where present')
    ap.add_argument('--reuse-images', action='store_true', help='Refresh image hashes without rendering only after verifying every existing card is visually unchanged')
    ap.add_argument('--stamp-plain', action='store_true', help='Only rewrite the source fingerprints in data/plain-language.json, after re-reviewing the texts, and exit')
    args = ap.parse_args()
    if args.stamp_plain:
        stamp_plain(json.loads((ROOT / 'data/discoveries.json').read_text()))
        return
    install_english_chrome(ROOT)
    if args.reuse_images and (args.force or args.no_images):
        ap.error('--reuse-images cannot be combined with --force or --no-images')
    items = json.loads((ROOT / 'data/discoveries.json').read_text())
    archive_path = ROOT / 'data/archived-discoveries.json'
    archived = json.loads(archive_path.read_text()) if archive_path.exists() else []
    models = json.loads((ROOT / 'data/models.json').read_text())
    vulns = json.loads((ROOT / 'data/vulnerabilities.json').read_text())
    validate_inputs(items, archived, models, vulns)
    plain = load_plain()
    validate_plain(plain)
    plain = usable_plain(plain, items)
    write_page_summaries(items, models)
    write_hero_pulse(items)
    write_plain_home(items, plain)
    from generate_insights import write_insights
    write_insights(items, models, plain, root=ROOT)
    write_home_browse(items)
    if not args.no_images:
        render_cards(items + archived, args.force, args.reuse_images)
    write_discovery_pages(items, models, not args.no_images, plain=plain)
    write_discovery_pages(archived, models, not args.no_images, archived=True, related_items=items)
    write_profile_pages(items, models, archived)
    write_catalog_evidence(items)
    write_security_pages(vulns)
    write_llms_txt(items, models)
    write_sitemap(items, models, archived, vulns)
    write_feed(items, vulns)
    write_exports(items, vulns)
    manifest = write_manifest(ROOT)
    write_component_jsonld(ROOT, manifest)
    write_api(items, vulns, models, archived, manifest=manifest)
    stamp_pages(ROOT, manifest['snapshot_sha256'])
    write_locale_pages(ROOT)
    print(f'{len(items)} share pages, profile pages, sitemap.xml, feed.xml and robots.txt written')


if __name__ == '__main__':
    main()
