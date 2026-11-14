import re
import unittest
import tempfile
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]


class RedirectParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonical, self.refresh, self.links = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical.append(attrs.get('href'))
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
            self.refresh.append(attrs.get('content', ''))
        if tag == 'a' and 'href' in attrs:
            self.links.append(attrs['href'])


def is_compatibility_redirect(page, seen, root):
    if page.parent != root / 'profiles' or not page.name.startswith('org-'):
        return False
    parser = RedirectParser()
    parser.feed(page.read_text())
    if len(parser.canonical) != 1 or len(parser.refresh) != 1:
        return False
    match = re.fullmatch(r'0;\s*url=([^\s]+)', parser.refresh[0], re.I)
    if not match or match[1] not in parser.links:
        return False
    target = (page.parent / match[1]).resolve()
    if target == page or target not in seen or root not in target.parents:
        return False
    return parser.canonical[0] == 'https://marcello-pichini.github.io/ai-science-tracker/' + target.relative_to(root).as_posix()


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
            missing = [p.name for p in ROOT.glob(pattern) if p.resolve() not in seen
                       and not is_compatibility_redirect(p.resolve(), seen, ROOT)]
            self.assertEqual(missing, [], f'{pattern} not reachable through plain links: {missing[:5]}')

    def test_compatibility_redirect_requires_matching_reachable_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / 'profiles').mkdir()
            alias = root / 'profiles/org-old.html'
            target = root / 'profiles/org-new.html'
            target.write_text('Profile')
            alias.write_text('<link rel="canonical" href="https://marcello-pichini.github.io/ai-science-tracker/profiles/org-new.html">'
                             '<meta http-equiv="refresh" content="0; url=org-new.html">'
                             '<a href="org-new.html">Profile</a>')
            self.assertTrue(is_compatibility_redirect(alias, {target}, root))
            self.assertFalse(is_compatibility_redirect(alias, set(), root))
            alias.write_text(alias.read_text().replace('url=org-new.html', 'url=org-old.html'))
            self.assertFalse(is_compatibility_redirect(alias, {target}, root))

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
