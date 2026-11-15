import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


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

    def test_feed_lists_newest_records_with_catalog_dates(self):
        g = self.generator
        vuln = {'id': 'v1', 'title': 'V & flaw', 'summary': 's', 'organization': 'Org', 'checked_date': '2999-01-01', 'disclosure_date': '2998-01-01'}
        g.write_feed([self.record], [vuln], limit=5)
        root = ET.fromstring((g.ROOT / 'feed.xml').read_text())
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('a:entry', ns)
        self.assertEqual(root.find('a:title', ns).text, 'AI Science Tracker: additions and source checks')
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].find('a:title', ns).text, 'V & flaw')
        self.assertTrue(entries[0].find('a:updated', ns).text.startswith('2999-01-01'))
        self.assertEqual(root.find('a:updated', ns).text, '2999-01-01T00:00:00Z')

    def test_exports_preserve_vulnerability_caveats_and_neutralize_formulas(self):
        g = self.generator
        (g.ROOT / 'data').mkdir()
        vuln = json.loads((ROOT / 'data/vulnerabilities.json').read_text())[0]
        vuln.update(title='=formula', classification_note='+caveat', remediation_note='@scope')
        g.write_exports([dict(self.record, summary='\tformula')], [vuln])
        with (g.ROOT / 'data/vulnerabilities.csv').open(newline='') as f:
            row = next(csv.DictReader(f))
        self.assertEqual(row['title'], "'=formula")
        self.assertEqual(row['classification_note'], "'+caveat")
        self.assertEqual(row['remediation_note'], "'@scope")
        self.assertEqual(row['ai_attribution_date'], vuln['ai_attribution_date'])
        with (g.ROOT / 'data/discoveries.csv').open(newline='') as f:
            self.assertEqual(next(csv.DictReader(f))['summary'], "'\tformula")

    def test_api_fingerprint_changes_with_edits_and_preserves_old_files_on_write_failure(self):
        g = self.generator
        g.write_api([self.record], [], {'models': []}, [])
        index_path = g.ROOT / 'api/v1/index.json'
        before = json.loads(index_path.read_text())
        self.assertEqual(before['data_version_date'], before['latest_discovery_addition_date'])
        g.write_api([dict(self.record, summary='corrected')], [], {'models': []}, [])
        after = json.loads(index_path.read_text())
        self.assertNotEqual(before['catalog_sha256'], after['catalog_sha256'])
        self.assertEqual(before['data_version_date'], after['data_version_date'])
        g.write_api([self.record], [], {'models': []}, [dict(self.record, id='archived')])
        self.assertNotEqual(before['catalog_sha256'], json.loads(index_path.read_text())['catalog_sha256'])
        old = g.ROOT / 'api/v1/discoveries/old.json'
        old.write_text('{}')
        with patch.object(Path, 'write_text', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                g.write_api([self.record], [])
        self.assertTrue(old.exists())

    def test_card_hashes_detect_content_and_styles_changes(self):
        g = self.generator
        (g.ROOT / 'styles.css').write_text('style')
        with patch.object(g, 'screenshot', side_effect=lambda page, out: out.write_bytes(b'png')) as screenshot:
            g.render_cards([self.record], False)
            self.assertEqual(screenshot.call_count, 2)
            g.render_cards([self.record], False)
            self.assertEqual(screenshot.call_count, 2)
            g.render_cards([dict(self.record, title='Changed')], False)
            self.assertEqual(screenshot.call_count, 3)
            (g.ROOT / 'styles.css').write_text('changed')
            g.render_cards([self.record], False)
            self.assertEqual(screenshot.call_count, 5)

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

    def test_legacy_organization_urls_redirect_to_current_profiles(self):
        g = self.generator
        self.record['organization'] = 'First Lab; Second Lab AND Third Lab'
        g.write_profile_pages([self.record], {'families': []})
        current = g.ROOT / 'profiles/org-first-lab.html'
        legacy = g.ROOT / 'profiles/org-first-lab-second-lab-and-third-lab.html'
        self.assertTrue(current.is_file())
        self.assertTrue(legacy.is_file())
        text = legacy.read_text()
        self.assertIn('org-first-lab.html', text)
        self.assertIn(f'rel="canonical" href="{g.BASE}profiles/org-first-lab.html"', text)
        self.assertIn('href="org-first-lab.html"', text)
        self.assertEqual(g.lead_org('First Lab AND Second Lab'), 'First Lab')
        self.assertEqual(g.lead_org('First Lab, Second Lab'), 'First Lab')

    def test_archive_only_profiles_redirect_without_overwriting_active_profiles(self):
        g = self.generator
        active = dict(self.record, organization='Active Lab', ai_technology='Boltz', title='Active Boltz')
        old = dict(self.record, id='old', organization='Former Lab; Partner', ai_technology='Boltz', title='Boltz old')
        g.write_profile_pages([active], {'families': [{'id': 'boltz', 'name': 'Boltz', 'discoveries': [active['id']]}]}, [old])
        org = (g.ROOT / 'profiles/org-former-lab.html').read_text()
        self.assertIn('href="../share/old.html"', org)
        self.assertIn('share/old.html', org)
        self.assertNotIn('http-equiv="refresh"', (g.ROOT / 'profiles/family-boltz.html').read_text())
        g.write_profile_pages([self.record], {'families': []}, [old])
        family = (g.ROOT / 'profiles/family-boltz.html').read_text()
        self.assertIn('href="../share/old.html"', family)
        self.assertIn(f'rel="canonical" href="{g.BASE}share/old.html"', family)
        other = dict(old, id='other')
        g.write_profile_pages([self.record], {'families': []}, [old, other])
        self.assertIn('href="index.html"', (g.ROOT / 'profiles/org-former-lab.html').read_text())
        self.assertIn('href="index.html"', (g.ROOT / 'profiles/family-boltz.html').read_text())

    def test_invalid_input_is_rejected_before_writing_outputs(self):
        g = self.generator
        (g.ROOT / 'data').mkdir()
        for name, value in [('discoveries', [self.record]), ('models', {'families': [], 'models': []}),
                            ('vulnerabilities', [{'id': 'invalid'}])]:
            (g.ROOT / f'data/{name}.json').write_text(json.dumps(value))
        with patch('sys.argv', ['generate_share.py', '--no-images']):
            with self.assertRaises(KeyError):
                g.main()
        self.assertFalse((g.ROOT / 'share').exists())

    def test_long_collaborator_list_keeps_the_canonical_profile(self):
        g = self.generator
        self.record['organization'] = 'First Lab; ' + 'Long partner institution ' * 20
        pages = g.write_profile_pages([self.record], {'families': [], 'models': []})
        self.assertIn('profiles/org-first-lab.html', pages)
        self.assertTrue((g.ROOT / 'profiles/org-first-lab.html').exists())
        self.assertTrue(all(len(Path(page).name.encode('utf-8')) <= 255 for page in pages))

    def test_archived_discovery_has_a_page_but_does_not_enter_active_outputs(self):
        g = self.generator
        archived = dict(self.record, id='archived', organization='Former Lab; Partner', summary='Archived: outside the catalog scope.')
        (g.ROOT / 'data').mkdir()
        for name, value in [('discoveries', [self.record]), ('archived-discoveries', [archived]),
                            ('models', {'families': [], 'models': []}), ('vulnerabilities', [])]:
            (g.ROOT / f'data/{name}.json').write_text(json.dumps(value))
        with patch('sys.argv', ['generate_share.py', '--no-images']):
            g.main()
        page = (g.ROOT / 'share/archived.html').read_text()
        self.assertIn('Archived: outside the catalog scope.', page)
        self.assertNotIn('#discovery=archived', page)
        self.assertNotIn('org-former-lab.html', page)
        self.assertIn('share/archived.html', (g.ROOT / 'sitemap.xml').read_text())
        self.assertNotIn('org-former-lab.html', (g.ROOT / 'sitemap.xml').read_text())
        self.assertNotIn('archived', (g.ROOT / 'feed.xml').read_text())
        self.assertNotIn('archived', (g.ROOT / 'data/discoveries.csv').read_text())
        api = json.loads((g.ROOT / 'api/v1/index.json').read_text())
        self.assertEqual(api['counts']['discoveries'], 1)
        self.assertFalse((g.ROOT / 'api/v1/discoveries/archived.json').exists())
        self.assertNotIn('Former Lab', (g.ROOT / 'profiles/index.html').read_text())
        legacy = (g.ROOT / 'profiles/org-former-lab-partner.html').read_text()
        self.assertIn(f'rel="canonical" href="{g.BASE}share/archived.html"', legacy)
        self.assertIn('content="0; url=../share/archived.html"', legacy)
        self.assertIn('href="../share/archived.html"', legacy)

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
        self.assertIn('catalog of 1 entries about scientific results', text)
        self.assertIn(g.BASE + 'data/discoveries.json', text)

