"""First-party blog discovery: real dates, pagination and explicit access limitations."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from harvest import blog_sources as blogs, disc, fetch, known
from harvest.run_disc import is_known
from harvest import run_blogs


class BlogSourceTest(unittest.TestCase):
    def test_source_registry_is_allowlisted_and_directly_selectable(self):
        for name, source in blogs.SOURCES.items():
            fetch.check_url(source['url'])
            self.assertIn(name, disc.ADAPTERS)

    def test_rss_dates_survive_the_daily_date_filter(self):
        xml = '''<rss><channel><item><title>AI discovers new protein chemistry</title>
        <link>https://www.microsoft.com/en-us/research/blog/protein/</link>
        <pubDate>Wed, 18 Nov 2026 12:30:00 GMT</pubDate></item></channel></rss>'''
        report = {}
        with patch.object(fetch, 'get_text', return_value=xml), contextlib.redirect_stderr(io.StringIO()):
            rows = list(disc.research_blog('microsoft-research', '2026-11-18', '2026-11-18', report))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['date'], '2026-11-18')
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(blogs.normalize_date('2026-02-30'), '')

    def test_atom_uses_alternate_article_link_and_publication_date(self):
        xml = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI experiment</title>
        <link rel="self" href="https://example.invalid/id"/>
        <link rel="alternate" href="https://news.mit.edu/2026/ai-experiment-1118"/>
        <published>2026-11-17T12:00:00Z</published><updated>2026-11-18T12:00:00Z</updated>
        </entry></feed>'''
        row = list(blogs.feed_items(xml))[0]
        self.assertEqual(row[1:3], ('https://news.mit.edu/2026/ai-experiment-1118', '2026-11-17'))

    def test_university_date_formats_and_separate_card_headings(self):
        self.assertEqual(blogs.normalize_date('09 Nov 2026'), '2026-11-09')
        self.assertEqual(blogs.normalize_date('12 November, 2026'), '2026-11-12')
        self.assertEqual(blogs.normalize_date('Nov 10'), '')
        html = '<h2>New AI tissue atlas</h2><p>Research announcement</p><a href="https://actu.epfl.ch/news/tissue-atlas/">(more…)</a><button>Load more</button>'
        report = {}
        rows = list(blogs.source_items('epfl-ai', lambda *a, **k: html, report))
        self.assertEqual(rows[0][:3], ('New AI tissue atlas', 'https://actu.epfl.ch/news/tissue-atlas/', ''))
        self.assertEqual(report['status'], 'partial')

    def test_html_next_pages_are_deduplicated_and_no_dates_are_invented(self):
        first = '''<article><a href="/blog/ai-protein/?utm_source=feed"><h2>AI protein experiment</h2></a>
        <time datetime="2026-11-18">November 18, 2026</time></article>
        <a href="/blog/ai-protein/">AI protein experiment with a longer card heading</a>
        <a href="/blog/?page=2" rel="next">Next</a>'''
        second = '''<a href="https://evil.invalid/blog/fake/">New AI finding</a>
        <a href="/blog/2026/11/17/ai-materials/">AI materials discovery</a>'''
        pages = {'https://ai.meta.com/blog/': first, 'https://ai.meta.com/blog/?page=2': second}
        report = {}
        rows = list(blogs.source_items('meta-ai', lambda url, **_: pages[url], report))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][2], '2026-11-18')
        self.assertEqual(rows[1][2], '')
        self.assertEqual(report['pages'], 2)

    def test_path_pagination_and_cycles_are_reported(self):
        pages = {'https://ai.meta.com/blog/': '<a href="/blog/a/">AI experiment</a><a rel="next" href="/blog/page/2/">Next</a>',
                 'https://ai.meta.com/blog/page/2/': '<a href="/blog/b/">AI molecule</a><a rel="next" href="/blog/">Next</a>'}
        report = {}
        rows = list(blogs.source_items('meta-ai', lambda url, **_: pages[url], report))
        self.assertEqual(len(rows), 2)
        self.assertEqual(report['status'], 'partial')
        self.assertIn('cycle', report['coverage'])

    def test_empty_blocked_and_dynamic_sources_are_not_successful_zero_news(self):
        for body in ('<html><h1>Access denied</h1></html>', '<html></html>'):
            report = {}
            self.assertEqual(list(blogs.source_items('meta-ai', lambda *a, **k: body, report)), [])
            self.assertEqual(report['status'], 'partial')
        report = {}
        rows = list(blogs.source_items('epfl-ai', lambda *a, **k:
                    '<a href="https://actu.epfl.ch/news/ai-tissue-atlas/">AI tissue atlas</a><button>Load more</button>', report))
        self.assertEqual(len(rows), 1)
        self.assertEqual(report['status'], 'partial')
        self.assertIn('dynamic', report['coverage'])
        report = {}
        def blocked(*args, **kwargs):
            raise OSError('blocked transport')
        list(blogs.source_items('meta-ai', blocked, report))
        self.assertEqual(report['status'], 'error')
        with patch.object(fetch, 'get_text', side_effect=OSError('blocked')), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(list(disc.research_blog('meta-ai')), [])
        self.assertIn('error', stderr.getvalue())

    def test_known_url_skips_even_when_listing_title_has_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            url = 'https://www.microsoft.com/en-us/research/blog/known/'
            (root / 'data/discoveries.json').write_text(json.dumps([{'id': 'a', 'title': 'Old title', 'source_url': url}]))
            index = known.Known(root)
            self.assertTrue(is_known(index, {'key': url, 'ids': [url], 'title': 'Different listing headline'}))

    def test_cli_persists_incomplete_source_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(fetch, 'get_text', side_effect=OSError('source unavailable')), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                result = run_blogs.main(['--from', '2026-11-01', '--to', '2026-11-18',
                                         '--sources', 'microsoft-research', '--out', str(output)])
            self.assertEqual(result, 1)
            coverage = json.loads((output / 'blog-coverage.json').read_text())
            self.assertEqual(coverage['sources'][0]['status'], 'error')
            self.assertEqual(coverage['unique_candidates'], 0)
            self.assertTrue((output / 'blog-leads.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
