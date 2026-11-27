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

    def test_agent_slices_cover_the_catalog_and_stay_small(self):
        ids = {d['id'] for d in json.loads((ROOT / 'data/discoveries.json').read_text())}
        api = ROOT / 'api/v1'
        self.assertEqual(len(json.loads((api / 'latest.json').read_text())['discoveries']), min(100, len(ids)))
        self.assertLessEqual(set(json.loads((api / 'doi-index.json').read_text())['dois'].values()), ids)
        for kind in ('fields', 'years'):
            rows = [r['id'] for p in (api / kind).glob('*.json') for r in json.loads(p.read_text())['discoveries']]
            self.assertEqual(sorted(rows), sorted(ids), kind)
            self.assertEqual([p.name for p in (api / kind).glob('*.json') if p.stat().st_size > 1_000_000], [], kind)

    def test_shared_translation_bundle_carries_no_catalog_data(self):
        for lang in LOCALES:
            self.assertLess((ROOT / lang / 'runtime.js').stat().st_size, 400_000, lang)
            self.assertNotIn('discoveries.js', (ROOT / lang / 'contact.html').read_text(encoding='utf-8'))
            self.assertIn('discoveries.js?v=', (ROOT / lang / 'index.html').read_text(encoding='utf-8'))

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

    def test_discovery_summaries_carry_no_reviewer_vocabulary(self):
        # Summaries become meta descriptions, og:description and JSON-LD abstracts; review jargon must stay internal.
        jargon = re.compile(r'\badmit(?:s|ted)?\b|\badmission\b|\bPrimary (?:Methods|Results)\b', re.I)
        records = json.loads((ROOT / 'data/discoveries.json').read_text(encoding='utf-8'))
        self.assertEqual([r['id'] for r in records if jargon.search(r['summary'])], [])

    def test_every_discovery_page_states_when_it_was_updated(self):
        # Freshness signal for search and answer engines: JSON-LD dateModified, the same visible date and sitemap lastmod.
        lastmod = {}
        for path in sorted((ROOT / 'share').glob('*.html')):
            text = path.read_text(encoding='utf-8')
            data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S).group(1))
            modified = data.get('dateModified')
            self.assertRegex(modified or '', r'^\d{4}-\d{2}-\d{2}$', path.name)
            self.assertEqual(data['mainEntity'].get('dateModified'), modified, path.name)
            self.assertIn(f'Entry updated <time datetime="{modified}">', text, path.name)
            lastmod[path.name] = modified
        sitemap = (ROOT / 'sitemap.xml').read_text(encoding='utf-8')
        for name, date in re.findall(r'<loc>[^<]*/share/([^<]+)</loc><lastmod>([^<]+)</lastmod>', sitemap):
            self.assertEqual(date, lastmod.get(name, date), name)


if __name__ == '__main__':
    unittest.main()
