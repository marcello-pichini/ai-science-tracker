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
<link rel="canonical" href="{base}share/{id}.html">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{site}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{base}share/{id}.html">
<meta property="og:image" content="{base}og/{img}.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#12367e">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2312367e'/%3E%3Cpath d='M8 24v-6M12 24v-11M16 24v-15M20 24v-8M24 24v-4' stroke='%23f2f6ff' stroke-width='2.6' stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preload" href="assets/fonts/schibsted-grotesk-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="styles.css">
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
    <div class="piatto">{article}</div>
    <p class="sez-sub"><a href="index.html#discovery={qid}">Open in the full catalog</a> for filters, charts and related discoveries.</p>
  </div></section>
</main>

{footer}
</body>
</html>
"""


def safe_url(u):
    return u if re.match(r'^https?://', u or '') else '#'


def discovery_article(d, fam, ui):
    """Same fields and markup as index.html's voce(), minus JS-only controls (the "Read
    more" truncation toggle and the "Copy link" button) that cannot work without script."""
    p = score(d)
    family = (f'<p class="modello">Family {esc(fam["name"])}: <a href="profile.html?family={quote(fam["id"])}">profile</a> '
              f'&middot; <a href="models.html#fam-{esc(fam["id"])}">models page</a></p>') if fam else ''
    tech = f'<p class="tech"><span>Technology:</span> {esc(d["ai_technology"])}</p>' if d['ai_technology'] else ''
    paper = f'<a href="{esc(safe_url(d["paper_url"]))}" rel="noopener">Paper</a>' if d['paper_url'] else ''
    return f"""<article class="voce" id="{esc(d['id'])}">
    <div class="voce-meta"><time datetime="{esc(d['publication_date'])}">{esc(nice_date(d['publication_date']))}</time><a href="profile.html?org={quote(lead_org(d['organization']))}">{esc(d['organization'])}</a></div>
    <h3>{esc(d['title'])}</h3>
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
                           id=esc(d['id']), qid=quote(d['id']), img=d['id'] if images else 'default',
                           header=header, footer=footer, lead=lead, article=article)
        (out / f'{d["id"]}.html').write_text('\n'.join(line.rstrip() for line in relocate(page).splitlines()) + '\n')


def write_sitemap(items, models):
    orgs = sorted({lead_org(d['organization']) for d in items})
    fams = sorted(f['id'] for f in models['families'] if f['discoveries'])
    # Announcement dates are not page-modification dates; omit lastmod until tracked.
    urls = ['', 'index.html', 'models.html', 'methodology.html', 'guide.html', 'profile.html', 'security.html']
    urls += [f'profile.html?org={quote(o)}' for o in orgs]
    urls += [f'profile.html?family={quote(f)}' for f in fams]
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
    write_sitemap(items, models)
    print(f'{len(items)} share pages, sitemap.xml and robots.txt written')


if __name__ == '__main__':
    main()
