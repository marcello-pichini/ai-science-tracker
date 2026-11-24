"""Search-engine rules checked on the generated site, so a later change cannot silently undo them.

Limits follow the site audit: titles up to 60 characters, meta descriptions of 110-160
characters, pages under the 2 MB crawl limit, no noindex page in the sitemap and no orphan
model-family profile.
"""
import html
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ('it', 'de', 'fr', 'es')
MAX_BYTES = 2 * 1024 * 1024
TITLE_MAX = 60
DESC_MIN, DESC_MAX = 110, 160

TITLE = re.compile(r'<title>(.*?)</title>', re.S)
DESC = re.compile(r'<meta name="description" content="([^"]*)"')
H1 = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)


def head(path):
    with path.open(encoding='utf-8', errors='ignore') as f:
        return f.read(20000)


def indexable(text):
    return 'name="robots" content="noindex' not in text and 'http-equiv="refresh"' not in text


def generated_pages():
    for folder in ('share', 'profiles'):
        for path in sorted((ROOT / folder).glob('*.html')):
            text = head(path)
            if indexable(text):
                yield path, text


class GeneratedSeoTest(unittest.TestCase):
    def test_public_pages_stay_under_crawl_limit(self):
        paths = [*ROOT.glob('*.html'), *(ROOT / 'share').glob('*.html'), *(ROOT / 'profiles').glob('*.html')]
        paths += [p for lang in LOCALES for p in (ROOT / lang).glob('*.html')]
        heavy = [f'{p.relative_to(ROOT)} {p.stat().st_size}' for p in paths if p.stat().st_size > MAX_BYTES]
        self.assertEqual(heavy, [])

    def test_translated_pages_load_the_shared_runtime(self):
        for lang in LOCALES:
            self.assertTrue((ROOT / lang / 'runtime.js').is_file(), lang)
            for path in (ROOT / lang).glob('*.html'):
                text = path.read_text(encoding='utf-8')
                if '<script>Object.assign(globalThis,{"AST_MESSAGES"' in text:
                    self.fail(f'{path.relative_to(ROOT)} inlines the translation bundle')
                if 'dossier' not in path.name and 'id="lang-switch"' in text:
                    self.assertIn('runtime.js?v=', text, path.relative_to(ROOT))

    def test_generated_titles_and_descriptions_fit_search_snippets(self):
        problems = []
        for path, text in generated_pages():
            name = path.relative_to(ROOT)
            title = html.unescape(TITLE.search(text).group(1))
            h1 = H1.search(text)
            full = html.unescape(re.sub(r'<[^>]+>', '', h1.group(1))).strip() if h1 else ''
            # Archived entries and still-duplicate short titles fall back to the full title by design.
            if len(title) > TITLE_MAX and not title.startswith('Archived:') and title != full:
                problems.append(f'{name}: title {len(title)}')
            desc = DESC.search(text)
            if desc and not DESC_MIN <= len(html.unescape(desc.group(1))) <= DESC_MAX:
                problems.append(f'{name}: description {len(html.unescape(desc.group(1)))}')
        self.assertEqual(problems[:20], [])

    def test_sitemap_lists_only_indexable_pages(self):
        base = 'https://aisciencetracker.org/'
        bad = []
        for url in re.findall(r'<loc>([^<]+)</loc>', (ROOT / 'sitemap.xml').read_text(encoding='utf-8')):
            rel = url.removeprefix(base) or 'index.html'
            if rel.endswith('/'):
                rel += 'index.html'
            path = ROOT / rel
            if path.suffix == '.html' and path.is_file() and not indexable(head(path)):
                bad.append(rel)
        self.assertEqual(bad[:20], [])

    def test_every_family_profile_has_an_incoming_link(self):
        linked = set()
        for path in (ROOT / 'share').glob('*.html'):
            linked.update(re.findall(r'profiles/family-([^".]+)\.html', path.read_text(encoding='utf-8')))
        families = [f['id'] for f in json.loads((ROOT / 'data' / 'models.json').read_text())['families']
                    if (ROOT / 'profiles' / f'family-{f["id"]}.html').is_file()
                    and indexable(head(ROOT / 'profiles' / f'family-{f["id"]}.html'))]
        self.assertEqual(sorted(set(families) - linked), [])

    def test_discovery_records_use_article_schema(self):
        sample = next(p for p in sorted((ROOT / 'share').glob('*.html')) if indexable(head(p)))
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', sample.read_text(encoding='utf-8'), re.S)
        types = [json.loads(b).get('mainEntity', {}).get('@type') for b in blocks]
        self.assertIn('Article', types)


if __name__ == '__main__':
    unittest.main()
