import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CrawlableLinkTests(unittest.TestCase):
    def test_every_static_page_is_reachable_from_the_home_page_without_script(self):
        seen, queue = set(), [ROOT / 'index.html']
        while queue:
            page = queue.pop()
            if page in seen or not page.is_file():
                continue
            seen.add(page)
            for href in re.findall(r'href="([^"]+)"', page.read_text()):
                if re.match(r'^(https?:|mailto:|data:|#)', href):
                    continue
                target = (page.parent / href.split('#')[0].split('?')[0]).resolve()
                if target.suffix == '.html' and ROOT in target.parents:
                    queue.append(target)
        for pattern in ('share/*.html', 'profiles/*.html'):
            missing = [p.name for p in ROOT.glob(pattern) if p.resolve() not in seen]
            self.assertEqual(missing, [], f'{pattern} not reachable through plain links: {missing[:5]}')

    def test_data_fetches_use_the_browser_cache(self):
        for page in ROOT.glob('*.html'):
            self.assertNotIn('no-store', page.read_text(), page.name)

    def test_404_page_matches_the_site_frame_and_is_not_indexed(self):
        page = (ROOT / '404.html').read_text()
        index = (ROOT / 'index.html').read_text()
        self.assertIn('<base href="https://marcello-pichini.github.io/ai-science-tracker/">', page)
        self.assertIn('name="robots" content="noindex"', page)
        self.assertIn('href="styles.css"', page)
        self.assertNotIn('<style', page)
        nav = lambda text: re.search(r'<nav class="menu".*?</nav>', text, re.S).group(0).replace(' aria-current="page"', '')
        self.assertEqual(nav(page), nav(index))


if __name__ == '__main__':
    unittest.main()
