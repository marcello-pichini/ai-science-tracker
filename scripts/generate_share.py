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
  python3 scripts/generate_share.py            # pages, sitemap, robots, and any missing cards
  python3 scripts/generate_share.py --force    # also re-render every card (after a design or data change)
  python3 scripts/generate_share.py --no-images  # skip Chrome (pages then point at og/default.png)

Cards use styles.css and the self-hosted font, so they follow docs/DESIGN.md automatically.
Discovery pages are generated, not hand-written, but still obey docs/DESIGN.md: same frame,
same stylesheet, same wording as the live catalog, extracted from index.html rather than
retyped, so they automatically track any nav or footer change made there.
"""
import argparse
import datetime
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://marcello-pichini.github.io/ai-science-tracker/'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
SITE = 'AI Science Tracker'
DEFAULT_ALT = 'Preview card: AI Science Tracker, scientific discoveries enabled by AI, tracked from official announcements since 2020.'
NOT_ROOT_RELATIVE = re.compile(r'^(https?:|data:|mailto:|#|\.\./)')


def esc(s):
    return html.escape(str(s), quote=True)


def lead_org(name):
    """Same rule as index.html: organizations listed together count under the first one named."""
    return name.replace(' and ', ',').split(',')[0].strip()


def score(d):
    r = d['relevance']
    return round((r['impact'] + r['validation'] + r['novelty']) / 3 * 20)


def nice_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f'{d.day} {d:%b %Y}'


def clip(text, n):
    return text if len(text) <= n else text[:n - 1].rsplit(' ', 1)[0].rstrip(',;:') + '…'


def relocate(fragment):
    """Rewrite href/src values for a page one directory below the site root (share/id.html),
    so root-relative links copied verbatim out of a top-level page (index.html, "styles.css", ...)
    still resolve. Absolute, data:, mailto:, anchor and already-relocated links are left alone."""
    def fix(m):
        attr, quote_char, value = m.group(1), m.group(2), m.group(3)
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


def render_default(force):
    """Generic card used by the site pages' og:image."""
    out = ROOT / 'og' / 'default.png'
    if out.exists() and not force:
        return
    (ROOT / 'og').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / 'card.html'
        page.write_text(card_html((ROOT / 'styles.css').as_uri(), 'Scientific discoveries enabled by AI',
                                  'Tracked from official announcements since 2020'))
        screenshot(page, out)


def render_cards(items, force):
    todo = [d for d in items if force or not (ROOT / 'og' / f'{d["id"]}.png').exists()]
    (ROOT / 'og').mkdir(exist_ok=True)
    css = (ROOT / 'styles.css').as_uri()
    with tempfile.TemporaryDirectory() as tmp:
        for n, d in enumerate(todo, 1):
            page = Path(tmp) / 'card.html'
            row = (f'<p class="og-score"><span class="metro"><i style="width:{score(d)}%"></i></span> '
                   f'Relevance {score(d)} · {esc(d["field"])}</p>')
            page.write_text(card_html(css, esc(clip(d['title'], 150)),
                                      f'{esc(d["organization"])} · {nice_date(d["publication_date"])}', row))
            screenshot(page, ROOT / 'og' / f'{d["id"]}.png')
            print(f'card {n}/{len(todo)} {d["id"]}', file=sys.stderr)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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
<body>
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
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'


def jsonld(data):
    """Inline JSON-LD; '<' is escaped so record text can never close the script element."""
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return f'<script type="application/ld+json">\n{text}\n</script>'


def discovery_jsonld(d):
    # WebPage, not Article: the announcement date is not when this page was published.
    data = {'@context': 'https://schema.org/', '@type': 'WebPage', 'name': d['title'], 'description': clip(d['summary'], 300),
            'url': f'{BASE}share/{d["id"]}.html', 'inLanguage': 'en', 'license': LICENSE_URL, 'creator': CREATOR,
            'isPartOf': {'@type': 'Dataset', 'name': 'AI Science Tracker discovery catalog', 'url': BASE},
            'about': {'@type': 'Thing', 'name': d['title']}, 'isBasedOn': d['source_url']}
    if d['paper_url']:
        data['citation'] = d['paper_url']
    return jsonld(data)


def profile_jsonld(name, desc, path, organization=False):
    data = {'@context': 'https://schema.org/', '@type': 'CollectionPage', 'name': name, 'description': desc,
            'url': BASE + path, 'inLanguage': 'en', 'license': LICENSE_URL, 'creator': CREATOR,
            'isPartOf': {'@type': 'Dataset', 'name': 'AI Science Tracker discovery catalog', 'url': BASE}}
    if organization:
        data['about'] = {'@type': 'Organization', 'name': name}
    return jsonld(data)


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def safe_url(u):
    return u if re.match(r'^https?://', u or '') else '#'


def discovery_article(d, fam, ui, link_title=False):
    """Same fields and markup as index.html's voce(), minus JS-only controls (the "Read
    more" truncation toggle and the "Copy link" button) that cannot work without script."""
    p = score(d)
    family = (f'<p class="modello">Family {esc(fam["name"])}: <a href="profiles/family-{quote(fam["id"])}.html">profile</a> '
              f'&middot; <a href="models.html#fam-{esc(fam["id"])}">models page</a></p>') if fam else ''
    tech = f'<p class="tech"><span>Technology:</span> {esc(d["ai_technology"])}</p>' if d['ai_technology'] else ''
    paper = f'<a href="{esc(safe_url(d["paper_url"]))}" rel="noopener">Paper</a>' if d['paper_url'] else ''
    title_html = f'<a href="share/{esc(d["id"])}.html">{esc(d["title"])}</a>' if link_title else esc(d['title'])
    return f"""<article class="voce" id="{esc(d['id'])}">
    <div class="voce-meta"><time datetime="{esc(d['publication_date'])}">{esc(nice_date(d['publication_date']))}</time><a href="profiles/org-{slug(lead_org(d['organization']))}.html">{esc(d['organization'])}</a></div>
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


def write_discovery_pages(items, models, images):
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
        article = discovery_article(d, fam_by_discovery.get(d['id']), ui[d['id']])
        lead = f'{esc(d["organization"])} &middot; {esc(nice_date(d["publication_date"]))} &middot; {esc(d["field"])}'
        page = PAGE.format(title=esc(d['title']), site=SITE, desc=esc(clip(d['summary'], 200)), base=BASE,
                           path=f'share/{d["id"]}.html', img=d['id'] if images else 'default',
                           imgalt=esc(f'Preview card: {d["title"]}') if images else DEFAULT_ALT, jsonld=discovery_jsonld(d),
                           h2='<h2 class="vis-nascosto">Discovery</h2>', more=f'<a href="index.html#discovery={quote(d["id"])}">Open in the full catalog</a> for filters, charts and related discoveries.', extra=related_section(d, items),
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


def write_profile_pages(items, models):
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

    def years(rows):
        ys = sorted(d['publication_date'][:4] for d in rows)
        return ys[0] if ys[0] == ys[-1] else f'{ys[0]} to {ys[-1]}'

    def plural(n, one, many):
        return f'{n} {one if n == 1 else many}'

    def emit(name, title, lead, desc, rows, path, interactive, extra='', organization=False):
        articles = ''.join(discovery_article(d, fam_by_discovery.get(d['id']), ui[d['id']], link_title=True) for d in rows)
        more = f'<a href="{interactive}">Open the interactive profile</a> for the timeline, or <a href="profiles/index.html">browse all organizations and model families</a>.'
        page = PAGE.format(title=esc(title), site=SITE, desc=esc(desc), base=BASE, path=path, img='default', imgalt=DEFAULT_ALT,
                           header=header, footer=footer, lead=lead, article=articles, more=more, extra=extra,
                           h2='<h2 class="vis-nascosto">Discoveries</h2>', jsonld=profile_jsonld(title, desc, path, organization))
        (ROOT / path).write_text('\n'.join(line.rstrip() for line in relocate(page).splitlines()) + '\n')
        pages.append(path)

    slugs = {}
    for name, rows in by_org.items():
        assert slugs.setdefault(slug(name), name) == name, f'organization slug collision: {name}'
        emit(name, name, f'{plural(len(rows), "discovery", "discoveries")} from {years(rows)}',
             f'{plural(len(rows), "AI-enabled scientific discovery", "AI-enabled scientific discoveries")} tracked from {name}, with sources.',
             rows, f'profiles/org-{slug(name)}.html', f'profile.html?org={quote(name)}', organization=True)
    for fam in sorted(models['families'], key=lambda f: f['id']):
        rows = sorted((by_id[i] for i in fam['discoveries'] if i in by_id), key=lambda d: d['publication_date'], reverse=True)
        if not rows:
            continue
        rel = [m for m in models.get('models', []) if m.get('family') == fam['id']]
        emit(fam['name'], fam['name'], f'{plural(len(rows), "discovery", "discoveries")} name this family, {years(rows)}',
             f'{plural(len(rows), "AI-enabled scientific discovery", "AI-enabled scientific discoveries")} linked to the {fam["name"]} model family.',
             rows, f'profiles/family-{quote(fam["id"])}.html', f'profile.html?family={quote(fam["id"])}', releases_table(rel))
    labs = ''.join(f'<li><a href="profiles/org-{slug(n)}.html">{esc(n)}</a> ({len(r)})</li>' for n, r in sorted(by_org.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    fams = ''.join(f'<li><a href="profiles/family-{quote(f["id"])}.html">{esc(f["name"])}</a> ({len(f["discoveries"])})</li>' for f in sorted(models['families'], key=lambda f: (-len(f['discoveries']), f['name'])) if f['discoveries'])
    directory = f'<h2>Organizations</h2><ul class="elenco-profili">{labs}</ul><h2>Model families</h2><ul class="elenco-profili">{fams}</ul>'
    page = PAGE.format(title='Labs and model families', site=SITE, desc='Organizations and model families with at least one tracked AI-enabled discovery.', base=BASE,
                       path='profiles/index.html', img='default', imgalt=DEFAULT_ALT, header=header, footer=footer,
                       jsonld=profile_jsonld('Labs and model families', 'Organizations and model families with at least one tracked AI-enabled discovery.', 'profiles/index.html'),
                       lead=f'{len(by_org)} organizations and {len([f for f in models["families"] if f["discoveries"]])} model families', article=directory,
                       more='<a href="profile.html">Open the interactive directory</a>.', extra='', h2='')
    (ROOT / 'profiles/index.html').write_text('\n'.join(line.rstrip() for line in relocate(page).splitlines()) + '\n')
    pages.append('profiles/index.html')
    return pages


def write_llms_txt(items, models):
    """llms.txt: a plain summary for language-model crawlers. Counts come from the data so it never goes stale."""
    fields = len({d['field'] for d in items})
    orgs = len({lead_org(d['organization']) for d in items})
    newest = max(d['added_date'] for d in items)
    (ROOT / 'llms.txt').write_text(f'''# {SITE}

> A catalog of {len(items)} scientific discoveries enabled by AI across {fields} fields and {orgs} organizations since 2020. Each entry links to the original announcement by the organization that achieved the result. Figures are reported by the sources and are not independently verified; relevance scores are editorial judgments, not evidence grades.

Content is licensed CC BY 4.0 (attribute "{SITE}" with a link); site code is MIT. Model data comes from Epoch AI (CC BY 4.0). When citing a scientific claim, cite the original source linked on each entry, not this catalog.

## Browse
- [Discoveries]({BASE}index.html): filters, charts and the full list
- [Organizations and model families]({BASE}profiles/index.html): static profile pages
- [Models]({BASE}models.html): model releases linked to discoveries
- [Vuln discoveries]({BASE}security.html): publicly disclosed vulnerabilities with documented AI involvement, kept separate from the scientific count
- [Methodology]({BASE}methodology.html): what is included, how entries are verified and scored

## Data
- [discoveries.json]({BASE}data/discoveries.json): one record per discovery (schema: docs/discovery-schema.md in the repository)
- [models.json]({BASE}data/models.json): model releases and families
- [vulnerabilities.json]({BASE}data/vulnerabilities.json): vulnerability cases
- [sitemap.xml]({BASE}sitemap.xml): every static page
- Each discovery has its own page at {BASE}share/ID.html

## Notes
- Most recent catalog addition: {newest}. This is not a last-review date.
- The collection is manual and not exhaustive; most sources are the announcing organizations' own pages.
- Repository: https://github.com/marcello-pichini/ai-science-tracker
''')


def write_sitemap(items, models):
    orgs = sorted({lead_org(d['organization']) for d in items})
    fams = sorted(f['id'] for f in models['families'] if f['discoveries'])
    # Announcement dates are not page-modification dates; omit lastmod until tracked.
    urls = ['index.html', 'models.html', 'methodology.html', 'guide.html', 'profile.html', 'security.html']
    urls += ['profiles/index.html']
    urls += [f'profiles/org-{slug(o)}.html' for o in orgs]
    urls += [f'profiles/family-{quote(f)}.html' for f in fams]
    urls += [f'share/{quote(d["id"])}.html' for d in items]
    rows = ''.join(f'<url><loc>{esc(BASE + url)}</loc></url>\n' for url in urls)
    (ROOT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + '</urlset>\n')
    (ROOT / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-images', action='store_true')
    args = ap.parse_args()
    items = json.loads((ROOT / 'data/discoveries.json').read_text())
    models = json.loads((ROOT / 'data/models.json').read_text())
    if not args.no_images:
        render_default(args.force)
        render_cards(items, args.force)
    write_discovery_pages(items, models, not args.no_images)
    write_profile_pages(items, models)
    write_llms_txt(items, models)
    write_sitemap(items, models)
    print(f'{len(items)} share pages, profile pages, sitemap.xml and robots.txt written')


if __name__ == '__main__':
    main()
