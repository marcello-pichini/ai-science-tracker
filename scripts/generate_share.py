#!/usr/bin/env python3
"""Generate the files that make discoveries shareable and the site indexable.

Outputs (all generated, never edit by hand; rerun this script instead):
  og/<id>.png      1200x630 social preview card, rendered with headless Chrome
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
import csv
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from model_families import discovery_links

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://aisciencetracker.org/'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
SITE = 'AI Science Tracker'
DEFAULT_ALT = 'Preview card: AI Science Tracker, scientific discoveries enabled by AI, tracked from official announcements since 2020.'
NOT_ROOT_RELATIVE = re.compile(r'^(https?:|data:|mailto:|#|\.\./)')


def esc(s):
    return html.escape(str(s), quote=True)


def lead_org(name):
    """Same rule as index.html: organizations listed together count under the first one named."""
    return name.split(';')[0].strip()


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


def describe(text, n=200, hard=230):
    """Meta description made of whole sentences: as many as fit in n characters, or the first
    sentence alone when it fits in hard; only longer first sentences fall back to clip()."""
    parts = SENTENCE_END.split(text.strip())
    out = ''
    for part in parts:
        candidate = f'{out} {part}'.strip()
        if len(candidate) > n:
            break
        out = candidate
    if not out and len(parts[0]) <= hard:
        out = parts[0]
    return out or clip(text, n)


def relocate(fragment):
    """Rewrite href/src values for a page one directory below the site root (share/id.html),
    so root-relative links copied verbatim out of a top-level page (index.html, "styles.css", ...)
    still resolve. Absolute, data:, mailto:, anchor and already-relocated links are left alone."""
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
    """Render each record's source-check disclosure and correction-issue link with the same
    assets/catalog-ui.js the live pages use (one Node process for all records), so a discovery
    page never repeats that wording or that URL-building logic in a second, Python copy."""
    cites_path = ROOT / 'data/citations.json'
    snapshot = json.loads(cites_path.read_text()) if cites_path.exists() else {}
    cites = snapshot.get('records', {})
    items = [dict(r, citation=dict(cites[r['id']], checked=snapshot.get('checked'))) if r['id'] in cites else r for r in items]
    script = ("require(process.argv[1]);"
              "const items = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "const out = {};"
              "for (const r of items) out[r.id] = {details: CatalogUI.sourceDetails(r), correction: CatalogUI.correctionUrl(r)};"
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
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                    '--force-device-scale-factor=1', '--window-size=1200,630',
                    '--virtual-time-budget=2000', f'--screenshot={out}', page.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
<meta name="twitter:image:alt" content="{imgalt}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#12367e">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2312367e'/%3E%3Cpath d='M8 24v-6M12 24v-11M16 24v-15M20 24v-8M24 24v-4' stroke='%23f2f6ff' stroke-width='2.6' stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preload" href="assets/fonts/schibsted-grotesk-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="styles.css">
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
                        'https://huggingface.co/datasets/marcello-pichini/ai-science-tracker']}
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'


def jsonld(data):
    """Inline JSON-LD; '<' is escaped so record text can never close the script element."""
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return f'<script type="application/ld+json">\n{text}\n</script>'


def breadcrumb(name, path):
    return {'@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'AI Science Tracker', 'item': BASE + 'index.html'},
        {'@type': 'ListItem', 'position': 2, 'name': name, 'item': BASE + path}]}


def discovery_jsonld(d):
    # WebPage, not Article: the announcement date is not when this page was published.
    data = {'@context': 'https://schema.org/', '@type': 'WebPage', 'name': d['title'], 'description': clip(d['summary'], 300),
            'url': f'{BASE}share/{d["id"]}.html', 'inLanguage': 'en', 'license': LICENSE_URL, 'creator': CREATOR, 'publisher': PUBLISHER,
            'isPartOf': {'@type': 'Dataset', '@id': BASE + 'index.html#dataset', 'name': 'AI Science Tracker discovery catalog', 'url': BASE + 'index.html'},
            'breadcrumb': breadcrumb(d['title'], f'share/{d["id"]}.html'),
            'about': {'@type': 'Thing', 'name': d['title']}, 'isBasedOn': d['source_url']}
    if d['paper_url']:
        data['citation'] = d['paper_url']
    return jsonld(data)


def profile_jsonld(name, desc, path, organization=False):
    data = {'@context': 'https://schema.org/', '@type': 'CollectionPage', 'name': name, 'description': desc,
            'url': BASE + path, 'inLanguage': 'en', 'license': LICENSE_URL, 'creator': CREATOR, 'publisher': PUBLISHER,
            'isPartOf': {'@type': 'Dataset', '@id': BASE + 'index.html#dataset', 'name': 'AI Science Tracker discovery catalog', 'url': BASE + 'index.html'},
            'breadcrumb': breadcrumb(name, path)}
    if organization:
        data['about'] = {'@type': 'Organization', 'name': name}
    return jsonld(data)


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def safe_url(u):
    return u if re.match(r'^https?://', u or '') else '#'


def discovery_article(d, fam, ui, link_title=False, archived=False):
    """Same fields and markup as index.html's voce(), minus JS-only controls (the "Read
    more" truncation toggle and the "Copy link" button) that cannot work without script."""
    p = score(d)
    family = (f'<p class="modello">Family {esc(fam["name"])}: <a href="profiles/family-{quote(fam["id"])}.html">profile</a> '
              f'&middot; <a href="models.html#fam-{esc(fam["id"])}">models page</a></p>') if fam else ''
    tech = f'<p class="tech"><span>Technology:</span> {esc(d["ai_technology"])}</p>' if d['ai_technology'] else ''
    paper = f'<a href="{esc(safe_url(d["paper_url"]))}" rel="noopener">Paper</a>' if d['paper_url'] else ''
    title_html = f'<a href="share/{esc(d["id"])}.html">{esc(d["title"])}</a>' if link_title else esc(d['title'])
    organization = esc(d['organization']) if archived else f'<a href="profiles/org-{slug(lead_org(d["organization"]))}.html">{esc(d["organization"])}</a>'
    return f"""<article class="voce" id="{esc(d['id'])}">
    <div class="voce-meta"><time datetime="{esc(d['publication_date'])}">{esc(nice_date(d['publication_date']))}</time>{organization}</div>
    <h3>{title_html}</h3>
    <p class="sommario">{esc(d['summary'])}</p>
    {tech}
    {family}
    <div class="voce-footer">
      <span class="punteggio" title="Impact {d['relevance']['impact']}/5, validation {d['relevance']['validation']}/5, novelty {d['relevance']['novelty']}/5">Relevance {p}<span class="metro" aria-hidden="true"><i style="width:{p}%"></i></span></span>
      <span class="etich">{esc(d['field'])}</span>
      <span class="collegamenti"><a href="{esc(safe_url(d['source_url']))}" rel="noopener">Original source</a>{paper} <a class="correction-link" href="{esc(ui['correction'])}" rel="noopener">Suggest a correction</a></span>
    </div>
    {ui['details']}
  </article>"""


def related_section(d, items):
    """Plain anchors to a few newer-first siblings, so every discovery page has inbound links
    from other pages (not only the sitemap). Capped at 3 per list to avoid near-duplicate blocks."""
    def block(title, rows):
        rows = rows[:3]
        if not rows:
            return ''
        lis = ''.join(f'<li><a href="share/{esc(r["id"])}.html">{esc(r["title"])}</a> &middot; {esc(nice_date(r["publication_date"]))}</li>' for r in rows)
        return f'<h2>{title}</h2><ul>{lis}</ul>'
    newest = sorted((r for r in items if r['id'] != d['id']), key=lambda r: r['publication_date'], reverse=True)
    org = lead_org(d['organization'])
    same_org = [r for r in newest if lead_org(r['organization']) == org]
    same_field = [r for r in newest if r['field'] == d['field'] and r not in same_org[:3]]
    body = block(f'More from {esc(org)}', same_org) + block(f'More in {esc(d["field"])}', same_field)
    return f'\n  <section class="sez"><div class="wrap"><div class="prosa">{body}</div></div></section>' if body else ''


def write_discovery_pages(items, models, images, archived=False):
    """Each page is a full, self-canonical page in the shared frame, indexable without
    JavaScript (IMP-011) — replacing the earlier noindex/meta-refresh stub."""
    out = ROOT / 'share'
    out.mkdir(exist_ok=True)
    header, footer = site_frame()
    fam_by_discovery = {}
    for f in models['families']:
        for did in f['discoveries']:
            fam_by_discovery.setdefault(did, f)
    ui = run_catalog_ui(items)
    for d in items:
        has_image = images or (ROOT / 'og' / f'{d["id"]}.png').is_file()
        article = discovery_article(d, fam_by_discovery.get(d['id']), ui[d['id']], archived=archived)
        more = ('<a href="index.html">Browse the current catalog</a>.' if archived else
                f'<a href="index.html#discovery={quote(d["id"])}">Open in the full catalog</a> for filters, charts and related discoveries.')
        lead = f'{esc(d["organization"])} &middot; {esc(nice_date(d["publication_date"]))} &middot; {esc(d["field"])}'
        page = PAGE.format(title=esc(d['title']), site=SITE, desc=esc(describe(d['summary'])), base=BASE,
                           path=f'share/{d["id"]}.html', img=d['id'] if has_image else 'default',
                           imgalt=esc(f'Preview card: {d["title"]}') if has_image else DEFAULT_ALT, jsonld=discovery_jsonld(d),
                           h2='<h2 class="vis-nascosto">Discovery</h2>', more=more, extra=related_section(d, items),
                           header=header, footer=footer, lead=lead, article=article)
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
        return '<ul>' + ''.join(f'<li><a href="index.html#discovery={quote(d["id"])}">{esc(d["title"])}</a></li>' for d in records) + '</ul>' if records else '<p>No scientific uses are linked in this catalog.</p>'

    def test_context(d):
        value = d.get('evidence', {}).get('test_type')
        return 'Not annotated in this catalog' if not value else 'Test context unspecified in annotation' if value == 'not reported' else value

    def groups(title, key):
        return f'<h3>{title}</h3>' + ''.join(f'<details><summary>{esc(label)} · {len(group)} linked records</summary>{members(group)}</details>' for label, group in ((label, [d for d in rows if key(d) == label]) for label in sorted({key(d) for d in rows})))

    # Stable two-pass sorting keeps equal-date examples in ID order.
    examples = sorted(sorted(rows, key=lambda d: d['id']), key=lambda d: d['publication_date'], reverse=True)[:3]
    return f'<section aria-label="Represented scientific uses"><h2>Where {esc(name)} appears in the catalog</h2><details class="source-details"><summary>Why linked?</summary><p>These associations match family names in discovery titles and technology text. They are not verified model-version assignments or causal attribution. Missing links do not establish absence of use. A record may link to multiple families.</p></details>' + (groups('Represented fields', lambda d: d['field']) + groups('Test contexts', test_context) + groups('Annotation coverage', lambda d: 'Evidence annotation present' if d.get('evidence') else 'Not annotated in this catalog') if rows else '<p>No scientific uses are linked in this catalog.</p>') + '<h3>Examples</h3><p>Up to three linked records, newest publication date first, then stable ID. This selection is not a ranking.</p>' + members(examples) + '</section>'


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
        legacy_names = {d['organization'].replace(' and ', ',').split(',')[0].strip(),
                        re.split(r'[,;]| and ', d['organization'], flags=re.I)[0].strip()}
        new = slug(lead_org(d['organization']))
        for legacy in legacy_names:
            old = slug(legacy)
            if old != new:
                aliases.setdefault(old, set()).add(new)

    def years(rows):
        ys = sorted(d['publication_date'][:4] for d in rows)
        return ys[0] if ys[0] == ys[-1] else f'{ys[0]} to {ys[-1]}'

    def plural(n, one, many):
        return f'{n} {one if n == 1 else many}'

    def emit(name, title, lead, desc, rows, path, interactive, extra='', organization=False, label='interactive profile', before=''):
        articles = ''.join(discovery_article(d, fam_by_discovery.get(d['id']), ui[d['id']], link_title=True) for d in rows)
        purpose = 'the timeline' if label == 'interactive profile' else 'charts and filters'
        more = f'<a href="{interactive}">Open the {label}</a> for {purpose}, or <a href="profiles/index.html">browse all organizations and model families</a>.'
        page = PAGE.format(title=esc(title), site=SITE, desc=esc(desc), base=BASE, path=path, img='default', imgalt=DEFAULT_ALT,
                           header=header, footer=footer, lead=lead, article=articles, more=more, extra=extra,
                           h2=before + '<h2 class="vis-nascosto">Discoveries</h2>', jsonld=profile_jsonld(title, desc, path, organization))
        (ROOT / path).write_text('\n'.join(line.rstrip() for line in relocate(page).splitlines()) + '\n')
        pages.append(path)

    slugs = {}
    for name, rows in by_org.items():
        assert slugs.setdefault(slug(name), name) == name, f'organization slug collision: {name}'
        emit(name, name, f'{plural(len(rows), "discovery", "discoveries")} from {years(rows)}',
             f'{plural(len(rows), "AI-enabled scientific discovery", "AI-enabled scientific discoveries")} tracked from {name}, with sources.',
             rows, f'profiles/org-{slug(name)}.html', f'profile.html?org={quote(name)}', organization=True)
    archived_orgs = {}
    for d in archived:
        legacy = slug(d['organization'].replace(' and ', ',').split(',')[0].strip())
        previous = slug(re.split(r'[,;]| and ', d['organization'], flags=re.I)[0].strip())
        lead = slug(lead_org(d['organization']))
        for old in {legacy, previous, lead}:
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
        emit(fam['name'], fam['name'], f'{plural(len(rows), "discovery", "discoveries")} name this family, {years(rows)}',
             f'{plural(len(rows), "AI-enabled scientific discovery", "AI-enabled scientific discoveries")} linked to the {fam["name"]} model family.',
             rows, f'profiles/family-{quote(fam["id"])}.html', f'profile.html?family={quote(fam["id"])}', releases_table(rel), before=family_summary(rows, fam['name']))
    for fid, ids in discovery_links(archived).items():
        if ids and fid not in active_families:
            redirect(f'family-{quote(fid)}.html', {f'../share/{quote(did)}.html' for did in ids})
    # Field and year collections answer searches such as "AI discoveries in biology" or "AI discoveries 2025".
    by_field, by_year = {}, {}
    for d in sorted(items, key=lambda d: d['publication_date'], reverse=True):
        by_field.setdefault(d['field'], []).append(d)
        by_year.setdefault(d['publication_date'][:4], []).append(d)
    for field, rows in sorted(by_field.items()):
        emit(field, f'AI discoveries in {field}', f'{plural(len(rows), "discovery", "discoveries")} from {years(rows)}',
             f'{plural(len(rows), "scientific discovery", "scientific discoveries")} in {field} made with AI, {years(rows)}, each linked to its original source.',
             rows, f'profiles/field-{slug(field)}.html', f'index.html?field={quote(field)}', label='filtered catalog')
    for year, rows in sorted(by_year.items(), reverse=True):
        emit(year, f'AI discoveries in {year}', f'{plural(len(rows), "discovery", "discoveries")} announced in {year}',
             f'{plural(len(rows), "scientific discovery", "scientific discoveries")} made with AI and announced in {year}, each linked to its original source.',
             rows, f'profiles/year-{year}.html', f'index.html?year={year}', label='filtered catalog')
    topics = ''.join(f'<li><a href="profiles/field-{slug(f)}.html">{esc(f)}</a> ({len(r)})</li>' for f, r in sorted(by_field.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    yearly = ''.join(f'<li><a href="profiles/year-{y}.html">{y}</a> ({len(r)})</li>' for y, r in sorted(by_year.items(), reverse=True))
    labs = ''.join(f'<li><a href="profiles/org-{slug(n)}.html">{esc(n)}</a> ({len(r)})</li>' for n, r in sorted(by_org.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    fams = ''.join(f'<li><a href="profiles/family-{quote(f["id"])}.html">{esc(f["name"])}</a> ({len(f["discoveries"])})</li>' for f in sorted(models['families'], key=lambda f: (-len(f['discoveries']), f['name'])) if f['discoveries'])
    directory = f'<h2>Fields</h2><ul class="elenco-profili">{topics}</ul><h2>Years</h2><ul class="elenco-profili">{yearly}</ul><h2>Organizations</h2><ul class="elenco-profili">{labs}</ul><h2>Model families</h2><ul class="elenco-profili">{fams}</ul>'
    page = PAGE.format(title='Labs and model families', site=SITE, desc='Organizations and model families with at least one tracked AI-enabled discovery.', base=BASE,
                       path='profiles/index.html', img='default', imgalt=DEFAULT_ALT, header=header, footer=footer,
                       jsonld=profile_jsonld('Labs and model families', 'Organizations and model families with at least one tracked AI-enabled discovery.', 'profiles/index.html'),
                       lead=f'{len(by_org)} organizations and {len([f for f in models["families"] if f["discoveries"]])} model families', article=directory,
                       more='<a href="profile.html">Open the interactive directory</a>.', extra='', h2='')
    (ROOT / 'profiles/index.html').write_text('\n'.join(line.rstrip() for line in relocate(page).splitlines()) + '\n')
    pages.append('profiles/index.html')
    current = set(pages)
    for old in out.glob('org-*.html'):
        if f'profiles/{old.name}' not in current:
            redirect(old.name, {'index.html'})
    return pages


def write_llms_txt(items, models):
    """llms.txt: a plain summary for language-model crawlers. Counts come from the data so it never goes stale."""
    fields = len({d['field'] for d in items})
    orgs = len({lead_org(d['organization']) for d in items})
    newest = max(d['added_date'] for d in items)
    (ROOT / 'llms.txt').write_text(f'''# {SITE}

> A catalog of {len(items)} entries about scientific results enabled by AI across {fields} fields and {orgs} organizations since 2020. Each entry links to an original paper, preprint or institutional announcement. Entry counts are not counts of independent findings: methodological contributions can overlap other entries, and one entry can describe several related results. Figures are reported by the sources and are not independently verified; relevance scores are coarse editorial judgments, not evidence grades.

Content is licensed CC BY 4.0 (attribute "{SITE}" with a link); site code is MIT. Epoch AI model data is CC BY 4.0. The separate SWE-bench selection (data/swe-bench.json) is CC BY-NC 4.0, for noncommercial reuse only; it is not covered by the catalog CC BY 4.0 grant. Additional numerical benchmarks (data/benchmarks/) retain per-component CC BY 4.0, CC BY-SA 4.0, MIT or Apache-2.0 terms; see docs/public-benchmarks.md. CharXiv adapted data is CC BY-SA 4.0. These components are excluded from the blanket catalog license and catalog Hugging Face export. When citing a scientific claim, cite the original source linked on each entry, not this catalog.

## Browse
- [Discoveries]({BASE}index.html): filters, charts and the full list
- [Organizations and model families]({BASE}profiles/index.html): static profile pages
- [Model progress]({BASE}model-progress.html): exact model comparison, ECI, benchmark evidence and recorded release rhythm
- [Search all collections]({BASE}search.html): literal retrieval with separate counts and match reasons
- [Antibiotic evidence dossier]({BASE}antibiotic-dossier.html): dated, source-bounded synthesis
- [Models]({BASE}models.html): model releases linked to discoveries
- [Vuln discoveries]({BASE}security.html): publicly disclosed vulnerabilities with documented AI involvement, kept separate from the scientific count
- [Methodology]({BASE}methodology.html): what is included, how entries are verified and scored

## Data
- [discoveries.json]({BASE}data/discoveries.json): active catalog entries (schema and counting unit: docs/discovery-schema.md in the repository)
- [models.json]({BASE}data/models.json): model releases and families
- [model-progress.json]({BASE}data/model-progress.json): separate Epoch capability/benchmark source entries; may overlap releases
- [Independent benchmark directory]({BASE}data/benchmarks/index.json): 10 separately licensed numerical snapshots; source-specific selections and limits
- [vulnerabilities.json]({BASE}data/vulnerabilities.json): vulnerability cases
- [sitemap.xml]({BASE}sitemap.xml): every static page
- [dataset.html]({BASE}dataset.html): downloads (JSON, CSV), schemas and the read-only static API at {BASE}api/v1/index.json
- [contributors.html]({BASE}contributors.html): maintainer, contributors and how to contribute
- [feed.xml]({BASE}feed.xml): Atom feed of discovery additions and vulnerability source checks
- Each discovery has its own page at {BASE}share/ID.html

## Notes
- Most recent catalog addition: {newest}. This is not a last-review date.
- The collection is manual and not exhaustive; most sources are the announcing organizations' own pages.
- Repository: https://github.com/marcello-pichini/ai-science-tracker
''')


def write_sitemap(items, models, archived=()):
    orgs = sorted({lead_org(d['organization']) for d in items})
    fams = sorted(f['id'] for f in models['families'] if f['discoveries'])
    # Announcement dates are not page-modification dates; omit lastmod until tracked.
    urls = ['index.html', 'models.html', 'methodology.html', 'guide.html', 'security.html', 'dataset.html', 'contributors.html', 'model-progress.html', 'antibiotic-dossier.html']
    urls += ['profiles/index.html']
    urls += [f'profiles/org-{slug(o)}.html' for o in orgs]
    urls += [f'profiles/family-{quote(f)}.html' for f in fams]
    urls += [f'profiles/field-{slug(f)}.html' for f in sorted({d['field'] for d in items})]
    urls += [f'profiles/year-{y}.html' for y in sorted({d['publication_date'][:4] for d in items}, reverse=True)]
    urls += [f'share/{quote(d["id"])}.html' for d in [*items, *archived]]
    rows = ''.join(f'<url><loc>{esc(BASE + url)}</loc></url>\n' for url in urls)
    (ROOT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + '</urlset>\n')
    (ROOT / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n')


def write_feed(items, vulns, limit=40):
    """Order discoveries by addition date and vulnerabilities by source-check date."""
    rows = []
    for d in items:
        rows.append((d['added_date'], d['publication_date'], f'share/{quote(d["id"])}.html', d['title'], d['summary'],
                     f'Discovery - {d["organization"]}'))
    for v in vulns:
        rows.append((v['checked_date'], v['disclosure_date'], f'security.html#{quote(v["id"])}', v['title'], v['summary'],
                     f'Vulnerability - {v["organization"]}'))
    rows = sorted(rows, reverse=True)[:limit]
    entries = ''.join(
        f'<entry><id>{esc(BASE + path)}</id><title>{esc(title)}</title><link href="{esc(BASE + path)}"/>'
        f'<updated>{added}T00:00:00Z</updated><category term="{esc(cat.split(" - ")[0].lower())}"/>'
        f'<summary>{esc(clip(summary, 300))} ({esc(cat)}; announced {announced})</summary></entry>\n'
        for added, announced, path, title, summary, cat in rows)
    (ROOT / 'feed.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f'<id>{BASE}feed.xml</id><title>{SITE}: additions and source checks</title>'
        f'<link rel="self" href="{BASE}feed.xml"/><link href="{BASE}"/>'
        f'<updated>{rows[0][0]}T00:00:00Z</updated><author><name>{SITE}</name></author>\n{entries}</feed>\n')


CSV_DISCOVERY = ['id', 'title', 'summary', 'field', 'ai_technology', 'organization', 'source_url', 'source_type', 'publication_date',
                 'added_date', 'verification_status', 'paper_url', 'impact', 'validation', 'novelty', 'catalog_entry_url', 'publication_status', 'test_type', 'tested', 'unknown', 'ai_role', 'evidence_urls', 'source_review', 'follow_up', 'follow_up_review', 'relationships']
CSV_VULN = ['id', 'title', 'product', 'ai_system', 'organization', 'disclosure_date', 'classification', 'cves', 'source_url',
            'ai_source_url', 'advisory_url', 'remediation', 'checked_date', 'summary', 'ai_role',
            'ai_attribution_date', 'classification_note', 'remediation_note', 'cvss', 'impacts']


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
    write_csv('data/vulnerabilities.csv', CSV_VULN, [dict(v, cves=';'.join(v['cves']), **{key: json.dumps(v.get(key, []), ensure_ascii=False, separators=(',', ':')) for key in ('cvss', 'impacts')}) for v in vulns])


def write_api(items, vulns, models=None, archived=()):
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
        'documentation': BASE + 'dataset.html'}
    (ROOT / 'api/v1/index.json').write_text(json.dumps(index, indent=2) + '\n')



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
            if key not in ('cvss', 'impacts'):
                v[key]
        cves = set(v['cves'])
        if any(rating['cve'] is not None and rating['cve'] not in cves for rating in v.get('cvss', [])) or any(not set(impact['cves']) <= cves for impact in v.get('impacts', [])):
            raise ValueError('Vulnerability evidence CVEs must belong to the case')
        for key in ('disclosure_date', 'ai_attribution_date', 'checked_date'):
            if key == 'ai_attribution_date' and v[key] is None:
                continue
            datetime.date.fromisoformat(v[key])
    models['families']
    models['models']


BROWSE_START, BROWSE_END = '<!-- browse:start -->', '<!-- browse:end -->'


def write_page_summaries(items, models):
    summaries = {
        'index.html': (f'<b>{len(items)} discoveries</b> in {len({d["field"] for d in items})} fields and '
                       f'{len({lead_org(d["organization"]) for d in items})} organizations since 2020. '
                       'Each mark below represents one discovery; taller means more relevant.'),
        'models.html': (f'<b>{len(models["models"])} releases</b> from leading labs since 2020, using Epoch AI data. '
                        f'<b>{sum(f.get("discovery_count", 0) > 0 for f in models["families"])} families</b> of models are matched by name '
                        f'to at least one of {len(items)} catalog discoveries, covering {len(models.get("linked_discoveries", []))} discoveries in total.')}
    for name, summary in summaries.items():
        path = ROOT / name
        if path.exists():
            path.write_text(re.sub(r'(<p class="lead" id="lead">).*?(</p>)',
                                   lambda m: m[1] + summary + m[2], path.read_text(), flags=re.S))


def write_home_browse(items):
    """Write plain links to every entry page into index.html, grouped by year, so search
    engines and readers without JavaScript reach each entry in one step from the home page."""
    path = ROOT / 'index.html'
    page = path.read_text()
    if BROWSE_START not in page:
        return
    years = {}
    for d in sorted(items, key=lambda d: d['publication_date'], reverse=True):
        years.setdefault(d['publication_date'][:4], []).append(d)
    fields = ' · '.join(f'<a href="profiles/field-{slug(f)}.html">{esc(f)}</a>' for f in sorted({d['field'] for d in items}))
    blocks = ''.join(
        f'    <details><summary>{y} ({len(rows)}) · <a href="profiles/year-{y}.html">page for {y}</a></summary><ul>'
        + ''.join(f'<li><a href="share/{esc(d["id"])}.html">{esc(d["title"])}</a></li>' for d in rows)
        + '</ul></details>\n' for y, rows in years.items())
    section = (f'{BROWSE_START}\n  <section class="sez" aria-labelledby="t-browse"><div class="wrap prosa">\n'
               f'    <h2 id="t-browse">All entries by year</h2>\n'
               f'    <p>Plain links to the page of each of the {len(items)} entries, newest first.</p>\n'
               f'    <p>By field: {fields}.</p>\n'
               f'{blocks}  </div></section>\n  {BROWSE_END}')
    start, end = page.index(BROWSE_START), page.index(BROWSE_END) + len(BROWSE_END)
    path.write_text(page[:start] + section + page[end:])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-images', action='store_true', help='Skip PNG rendering; reuse existing per-entry images where present')
    ap.add_argument('--reuse-images', action='store_true', help='Refresh image hashes without rendering only after verifying every existing card is visually unchanged')
    args = ap.parse_args()
    if args.reuse_images and (args.force or args.no_images):
        ap.error('--reuse-images cannot be combined with --force or --no-images')
    items = json.loads((ROOT / 'data/discoveries.json').read_text())
    archive_path = ROOT / 'data/archived-discoveries.json'
    archived = json.loads(archive_path.read_text()) if archive_path.exists() else []
    models = json.loads((ROOT / 'data/models.json').read_text())
    vulns = json.loads((ROOT / 'data/vulnerabilities.json').read_text())
    validate_inputs(items, archived, models, vulns)
    write_page_summaries(items, models)
    write_home_browse(items)
    if not args.no_images:
        render_cards(items + archived, args.force, args.reuse_images)
    write_discovery_pages(items, models, not args.no_images)
    write_discovery_pages(archived, models, not args.no_images, archived=True)
    write_profile_pages(items, models, archived)
    write_llms_txt(items, models)
    write_sitemap(items, models, archived)
    write_feed(items, vulns)
    write_exports(items, vulns)
    write_api(items, vulns, models, archived)
    print(f'{len(items)} share pages, profile pages, sitemap.xml, feed.xml and robots.txt written')


if __name__ == '__main__':
    main()
