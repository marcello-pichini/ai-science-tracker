import importlib.util
import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SharePageTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('generate_share', ROOT / 'scripts/generate_share.py')
        self.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.generator)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.generator.ROOT = Path(self.temp.name)
        (self.generator.ROOT / 'assets').mkdir()
        shutil.copyfile(ROOT / 'assets/catalog-ui.js', self.generator.ROOT / 'assets/catalog-ui.js')
        (self.generator.ROOT / 'index.html').write_text('<header class="header"><nav><a href="security.html" aria-current="page">Security</a></nav></header><footer class="footer"><a href="guide.html">Guide</a></footer>')
        self.record = dict(json.loads((ROOT / 'data/discoveries.json').read_text())[0], id='test-discovery', title='A <test> & result', summary='A complete summary with <markup> escaped.')

    def test_static_discovery_is_readable_indexable_and_links_stay_local(self):
        g = self.generator
        g.write_discovery_pages([self.record], {'families': []}, False)
        text = (g.ROOT / 'share/test-discovery.html').read_text()
        self.assertIn('A complete summary with &lt;markup&gt; escaped.', text)
        self.assertNotIn('noindex', text)
        self.assertNotIn('http-equiv="refresh"', text)
        self.assertIn('rel="canonical" href="https://marcello-pichini.github.io/ai-science-tracker/share/test-discovery.html"', text)
        self.assertIn('href="../security.html"', text)
        self.assertIn('href="../methodology.html"', text)
        self.assertNotIn('aria-current=', text)
        self.assertIn('record_id=test-discovery', text)
        self.assertIn('Source checked', text)
        self.assertFalse(any(line.rstrip() != line for line in text.splitlines()))

    def test_sitemap_includes_static_discoveries_and_security_without_false_dates(self):
        g = self.generator
        g.write_sitemap([self.record], {'families': []})
        root = ET.fromstring((g.ROOT / 'sitemap.xml').read_text())
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = [node.text for node in root.findall('s:url/s:loc', ns)]
        self.assertIn(g.BASE + 'security.html', urls)
        self.assertNotIn(g.BASE, urls)
        self.assertIn(g.BASE + 'index.html', urls)
        self.assertIn(g.BASE + 'share/test-discovery.html', urls)
        self.assertEqual(len(root.findall('s:url/s:lastmod', ns)), 0)

    def test_static_profiles_are_indexable_and_sitemap_uses_them(self):
        g = self.generator
        models = {'families': [{'id': 'fam-x', 'name': 'Fam X', 'discoveries': ['test-discovery']}], 'models': [{'name': 'M1', 'date': '2024-01-02', 'family': 'fam-x', 'link': 'https://example.org', 'access': 'API'}]}
        self.record['organization'] = 'Org & Co and Other'
        pages = g.write_profile_pages([self.record], models)
        self.assertEqual(sorted(pages), ['profiles/family-fam-x.html', 'profiles/index.html', 'profiles/org-org-co.html'])
        org = (g.ROOT / 'profiles/org-org-co.html').read_text()
        self.assertIn('A complete summary with &lt;markup&gt; escaped.', org)
        self.assertIn('rel="canonical" href="https://marcello-pichini.github.io/ai-science-tracker/profiles/org-org-co.html"', org)
        self.assertNotIn('noindex', org)
        self.assertIn('profile.html?org=Org%20%26%20Co', org)
        self.assertIn('M1', (g.ROOT / 'profiles/family-fam-x.html').read_text())
        g.write_sitemap([self.record], models)
        text = (g.ROOT / 'sitemap.xml').read_text()
        self.assertIn(g.BASE + 'profiles/org-org-co.html', text)
        self.assertNotIn('profile.html?org=', text)

    def test_structured_data_is_valid_and_script_safe(self):
        import re
        g = self.generator
        self.record['title'] = 'A </script><b>x</b> title'
        g.write_discovery_pages([self.record], {'families': []}, False)
        text = (g.ROOT / 'share/test-discovery.html').read_text()
        blocks = re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>', text, re.S)
        self.assertEqual(len(blocks), 1)
        data = json.loads(blocks[0])
        self.assertEqual(data['@type'], 'WebPage')
        self.assertEqual(data['name'], self.record['title'])
        self.assertEqual(data['isBasedOn'], self.record['source_url'])
        self.assertEqual(data['url'], g.BASE + 'share/test-discovery.html')
        self.assertNotIn('</script><b>', blocks[0])

    def test_llms_txt_counts_come_from_the_data(self):
        g = self.generator
        g.write_llms_txt([self.record], {'families': []})
        text = (g.ROOT / 'llms.txt').read_text()
        self.assertTrue(text.startswith('# AI Science Tracker'))
        self.assertIn('catalog of 1 scientific discoveries', text)
        self.assertIn(g.BASE + 'data/discoveries.json', text)

