import datetime
import json
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from model_families import discovery_links

FIELDS = {'biology', 'chemistry', 'medicine', 'materials', 'climate',
          'mathematics', 'physics', 'computer science', 'humanities',
          'multidisciplinary', 'other'}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(v for k, v in attrs if k in ('href', 'src') and v)


class CatalogTests(unittest.TestCase):
    def test_discovery_schema(self):
        discoveries = json.loads((ROOT / 'data/discoveries.json').read_text())
        self.assertTrue(discoveries)
        self.assertEqual(len(discoveries), len({d['id'] for d in discoveries}))
        keys = {'id', 'title', 'summary', 'field', 'ai_technology', 'organization',
                'source_url', 'source_type', 'publication_date', 'added_date',
                'verification_status', 'paper_url', 'relevance'}
        for d in discoveries:
            with self.subTest(discovery=d['id']):
                self.assertTrue(keys <= set(d))
                self.assertFalse(set(d) - keys - {'evidence', 'source_review', 'follow_up', 'follow_up_review', 'relationships'})
                if 'evidence' in d:
                    e = d['evidence']
                    self.assertEqual(set(e) - {'test_type'}, {'publication_status', 'tested', 'unknown', 'ai_role', 'evidence_urls'})
                    if 'test_type' in e:
                        levels = ['not reported', 'retrospective or benchmark', 'direct test', 'prospective or independent check', 'replication or operational use']
                        self.assertIn(e['test_type'], levels)
                        self.assertEqual(d['relevance']['validation'], levels.index(e['test_type']) + 1, 'validation follows the test type')
                    self.assertIn(e['publication_status'], {'Peer-reviewed paper', 'Preprint', 'Announcement only', 'Not reported'})
                    self.assertTrue(all(isinstance(e[k], str) and e[k] for k in ('tested', 'unknown', 'ai_role')))
                    self.assertTrue(e['evidence_urls'] and all(u.startswith('https://') for u in e['evidence_urls']))
                self.assertIn(d['field'], FIELDS)
                self.assertTrue(d['title'] and d['summary'] and d['organization'])
                self.assertIn(d['source_type'], {'press release', 'blog', 'paper', 'other'})
                self.assertIn(d['verification_status'], {'verified', 'needs verification'})
                for key in ('publication_date', 'added_date'):
                    datetime.date.fromisoformat(d[key])
                for key in ('source_url', 'paper_url'):
                    if d[key]:
                        self.assertIn(urlsplit(d[key]).scheme, {'http', 'https'})
                self.assertEqual(set(d['relevance']), {'impact', 'validation', 'novelty'})
                self.assertTrue(all(type(n) is int and 1 <= n <= 5
                                    for n in d['relevance'].values()))

    def test_model_links_and_attribution(self):
        data = json.loads((ROOT / 'data/models.json').read_text())
        discoveries = json.loads((ROOT / 'data/discoveries.json').read_text())
        ids = {d['id'] for d in discoveries}
        expected = discovery_links(discoveries)
        self.assertEqual({f['id']: f['discoveries'] for f in data['families'] if f['discoveries']},
                         {fid: links for fid, links in expected.items() if links})
        self.assertEqual(set(data), {'generated', 'source', 'models', 'families', 'linked_discoveries'})
        self.assertEqual(data['source']['url'], 'https://epoch.ai/data/ai-models')
        self.assertEqual(data['source']['license'], 'CC BY 4.0')
        linked = set()
        family_ids = {f['id'] for f in data['families']}
        for f in data['families']:
            self.assertLessEqual(set(f['discoveries']), ids)
            self.assertEqual(f['discovery_count'], len(f['discoveries']))
            self.assertEqual(f['model_count'], len(f['models']))
            self.assertEqual(f['models'], [m['name'] for m in data['models'] if m['family'] == f['id']])
            linked.update(f['discoveries'])
        self.assertEqual(set(data['linked_discoveries']), linked)
        self.assertTrue(all(m['family'] is None or m['family'] in family_ids for m in data['models']))

    def test_english_pages_and_local_assets(self):
        for name in ('index.html', 'models.html', 'methodology.html', 'security.html'):
            text = (ROOT / name).read_text()
            self.assertIn('lang="en"', text)
            self.assertIn('AI Science Tracker', text)
            self.assertNotIn('Discovery Atlas', text)
            links = Links()
            links.feed(text)
            for url in links.urls:
                parts = urlsplit(url)
                if not parts.scheme and not parts.netloc and parts.path:
                    self.assertFalse(parts.path.startswith('/'), url)
                    self.assertTrue((ROOT / unquote(parts.path)).is_file(), url)


if __name__ == '__main__':
    unittest.main()
