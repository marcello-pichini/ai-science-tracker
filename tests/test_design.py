"""Mechanical checks for docs/DESIGN.md: every page shares one frame and one stylesheet."""
import re
import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [ROOT / n for n in ('index.html', 'models.html', 'methodology.html', 'profile.html', 'guide.html', 'security.html', 'dataset.html')]
COLOR = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\(')


def css_outside_root(css):
    """Return CSS text with the custom-property blocks (:root rules) removed."""
    return re.sub(r':root[^{]*\{[^}]*\}', '', css)


class DesignTests(unittest.TestCase):
    def test_shared_script_urls_identify_the_current_content(self):
        digest = hashlib.sha256((ROOT / 'assets/catalog-ui.js').read_bytes()).hexdigest()[:12]
        for page in PAGES:
            sources = re.findall(r'<script src="([^"]+)"', page.read_text())
            for source in sources:
                if source.startswith('assets/catalog-ui.js'):
                    with self.subTest(page=page.name):
                        self.assertEqual(source, f'assets/catalog-ui.js?v={digest}')

    def test_pages_share_the_frame(self):
        self.assertTrue(PAGES)
        for page in PAGES:
            text = page.read_text()
            with self.subTest(page=page.name):
                self.assertIn('<html lang="en">', text)
                self.assertIn('href="styles.css"', text)
                self.assertIn('assets/fonts/schibsted-grotesk-latin.woff2', text)
                self.assertNotIn('<style', text)
                self.assertEqual(text.count('<h1'), 1)
                self.assertLessEqual(text.count('aria-current="page"'), 1)  # profile.html is not a menu item
                self.assertIn('og:image', text)
                self.assertIn('rel="canonical"', text)
                self.assertRegex(text, r'<title>[^<]*AI Science Tracker</title>')
                for nav in ('index.html', 'models.html', 'methodology.html', 'guide.html', 'security.html'):
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


if __name__ == '__main__':
    unittest.main()
