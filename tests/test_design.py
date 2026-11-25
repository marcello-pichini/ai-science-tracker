"""Mechanical checks for docs/DESIGN.md: every page shares one frame and one stylesheet."""
import re
import hashlib
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [ROOT / n for n in ('index.html', 'models.html', 'methodology.html', 'profile.html', 'guide.html', 'security.html', 'dataset.html', 'contributors.html', 'model-progress.html', 'search.html', 'antibiotic-dossier.html', 'dossiers.html', 'alphafold-dossier.html', 'materials-dossier.html', 'mathematics-dossier.html', 'seismology-dossier.html', 'astronomy-dossier.html', 'floods-dossier.html', 'vulnerabilities-dossier.html', 'model-releases-dossier.html', 'contact.html', 'insights.html')]
COLOR = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\(')


class RootLanguageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root_seen = False
        self.language = None

    def handle_starttag(self, tag, attrs):
        if tag == 'html' and not self.root_seen:
            self.root_seen = True
            self.language = dict(attrs).get('lang')


def document_language(text):
    parser = RootLanguageParser()
    parser.feed(text)
    return parser.language


def css_outside_root(css):
    """Return CSS text with the custom-property blocks (:root rules) removed."""
    return re.sub(r':root[^{]*\{[^}]*\}', '', css)


class DesignTests(unittest.TestCase):
    def test_root_language_allows_snapshot_attributes_and_rejects_missing_or_other_languages(self):
        for text, expected in (
            ('<html lang="en">', 'en'),
            ('<html lang="en" data-page-snapshot="abc">', 'en'),
            ("<HTML data-page-snapshot='abc' LANG='en'>", 'en'),
            ('<html lang="it" data-page-snapshot="abc">', 'it'),
            ('<html data-lang="en">', None),
            ('<!-- <html lang="en"> --><html>', None),
        ):
            with self.subTest(text=text):
                self.assertEqual(document_language(text), expected)

    def test_shared_script_urls_identify_the_current_content(self):
        digest = hashlib.sha256((ROOT / 'assets/catalog-ui.js').read_bytes()).hexdigest()[:12]
        for page in PAGES:
            sources = re.findall(r'<script src="([^"]+)"', page.read_text())
            for source in sources:
                if source.startswith('assets/catalog-ui.js'):
                    with self.subTest(page=page.name):
                        self.assertEqual(source, f'assets/catalog-ui.js?v={digest}')

    def test_shared_stylesheet_urls_identify_the_current_content(self):
        digest = hashlib.sha256((ROOT / 'styles.css').read_bytes()).hexdigest()[:12]
        for page in PAGES + [ROOT / '404.html']:
            href = re.search(r'<link rel="stylesheet" href="([^"]+)"', page.read_text()).group(1)
            self.assertEqual(href, f'styles.css?v={digest}', page.name)

    def test_pages_share_the_frame(self):
        self.assertTrue(PAGES)
        for page in PAGES:
            text = page.read_text()
            with self.subTest(page=page.name):
                self.assertEqual(document_language(text), 'en')
                self.assertRegex(text, r'href="styles.css\?v=[a-f0-9]{12}"')
                self.assertIn('assets/fonts/schibsted-grotesk-latin.woff2', text)
                self.assertNotIn('<style', text)
                self.assertEqual(text.count('<h1'), 1)
                self.assertLessEqual(text.count('aria-current="page"'), 1)  # profile.html is not a menu item
                self.assertIn('og:image', text)
                self.assertIn('rel="canonical"', text)
                self.assertRegex(text, r'<title>[^<]*AI Science Tracker</title>')
                menu = re.search(r'<nav class="menu".*?</nav>', text, re.S).group()
                self.assertLess(menu.index('href="security.html"'), menu.index('href="dossiers.html"'))
                self.assertLess(menu.index('href="dossiers.html"'), menu.index('href="methodology.html"'))
                self.assertIn('href="/"', menu)
                for nav in ('models.html', 'methodology.html', 'guide.html', 'security.html'):
                    self.assertIn(f'href="{nav}"', text)

    def test_no_hard_coded_colors_in_stylesheet(self):
        found = COLOR.findall(css_outside_root((ROOT / 'styles.css').read_text()))
        # Shadows and the SVG-in-CSS data URIs are the only tolerated literals.
        self.assertLessEqual(len(found), 3, found)

    def test_no_inline_colors_in_pages(self):
        for page in PAGES:
            text = re.sub(r'<link rel="icon"[^>]*>|<svg class="brand".*?</svg>', '', page.read_text(), flags=re.S)
            with self.subTest(page=page.name):
                self.assertNotRegex(text, r'style="[^"]*(#[0-9a-fA-F]{3,8}|rgb)')


    def test_pages_declare_a_content_policy_and_prerender_rules(self):
        generated = [next((ROOT / 'share').glob('*.html')), ROOT / 'profiles/index.html']
        for page in PAGES + generated:
            text = page.read_text()
            with self.subTest(page=page.name):
                self.assertIn("default-src 'self'", text)
                self.assertIn("connect-src 'self'", text)
                self.assertIn('<script type="speculationrules">', text)

if __name__ == '__main__':
    unittest.main()
