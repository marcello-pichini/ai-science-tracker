#!/usr/bin/env python3
"""Generate the files that make discoveries shareable and the site indexable.

Outputs (all generated, never edit by hand; rerun this script instead):
  og/<id>.png      1200x630 social preview card, rendered with headless Chrome
  share/<id>.html  stub page with Open Graph tags that redirects to index.html#discovery=<id>
  sitemap.xml, robots.txt

Usage:
  python3 scripts/generate_share.py            # stubs, sitemap, robots, and any missing cards
  python3 scripts/generate_share.py --force    # also re-render every card (after a design or data change)
  python3 scripts/generate_share.py --no-images  # skip Chrome (stubs then point at og/default.png)

Cards use styles.css and the self-hosted font, so they follow docs/DESIGN.md automatically.
"""
import argparse
import datetime
import html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://marcello-pichini.github.io/ai-science-tracker/'
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
SITE = 'AI Science Tracker'


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


STUB = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {site}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="noindex">
<link rel="canonical" href="{base}index.html#discovery={qid}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{site}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{base}share/{id}.html">
<meta property="og:image" content="{base}og/{img}.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0;url=../index.html#discovery={qid}">
<link rel="stylesheet" href="../styles.css">
</head>
<body>
<main class="wrap"><p><a href="../index.html#discovery={qid}">Open “{title}” in {site}</a></p></main>
</body>
</html>
"""


def write_stubs(items, images):
    out = ROOT / 'share'
    out.mkdir(exist_ok=True)
    for d in items:
        text = STUB.format(title=esc(d['title']), site=SITE, desc=esc(clip(d['summary'], 200)), base=BASE,
                           id=esc(d['id']), qid=quote(d['id']), img=d['id'] if images else 'default')
        (out / f'{d["id"]}.html').write_text(text)


def write_sitemap(items, models):
    orgs = sorted({lead_org(d['organization']) for d in items})
    fams = sorted(f['id'] for f in models['families'] if f['discoveries'])
    newest = max(d['publication_date'] for d in items)
    urls = ['', 'index.html', 'models.html', 'methodology.html', 'guide.html', 'profile.html']
    urls += [f'profile.html?org={quote(o)}' for o in orgs] + [f'profile.html?family={quote(f)}' for f in fams]
    rows = ''.join(f'<url><loc>{esc(BASE + u)}</loc><lastmod>{newest}</lastmod></url>\n' for u in urls)
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
    write_stubs(items, not args.no_images)
    write_sitemap(items, models)
    print(f'{len(items)} share pages, sitemap.xml and robots.txt written')


if __name__ == '__main__':
    main()
