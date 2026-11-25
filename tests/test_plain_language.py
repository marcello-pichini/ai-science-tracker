import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

REC = {'headline': 'A <short> headline', 'plain': 'Plain & simple.', 'why': 'It matters.', 'unknown': 'Not known yet.', 'source': 'x'}


class PlainLanguageTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('generate_share', ROOT / 'scripts/generate_share.py')
        self.g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.g)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.g.ROOT = Path(self.temp.name)
        (self.g.ROOT / 'assets').mkdir()
        shutil.copyfile(ROOT / 'styles.css', self.g.ROOT / 'styles.css')
        shutil.copyfile(ROOT / 'assets/catalog-ui.js', self.g.ROOT / 'assets/catalog-ui.js')
        shutil.copyfile(ROOT / 'security.html', self.g.ROOT / 'security.html')
        (self.g.ROOT / 'index.html').write_text(
            '<header class="header"><nav><a href="security.html">Security</a></nav></header>'
            '<footer class="footer"><a href="guide.html">Guide</a></footer>')
        base = json.loads((ROOT / 'data/discoveries.json').read_text())[0]
        self.a = dict(base, id='plain-a', title='Title A & <b>', field='biology')
        self.b = dict(base, id='plain-b', title='Title B', field='medicine')
        self.rec = dict(REC, source=self.g.plain_source(self.a))

    def page(self, plain, rows=None, has_image=False):
        rows = rows or [self.a]
        if has_image:
            (self.g.ROOT / 'og').mkdir(exist_ok=True)
            (self.g.ROOT / 'og/plain-a.png').write_bytes(b'x')
        self.g.write_discovery_pages(rows, {'families': []}, False, plain=plain)
        return (self.g.ROOT / 'share/plain-a.html').read_text()

    def test_record_with_plain_text_renders_the_full_short_version(self):
        text = self.page({'records': {'plain-a': self.rec}})
        for part in ('The short version', 'In plain words', 'Plain &amp; simple.', 'Why it matters', 'It matters.',
                     'What we still do not know', 'Not known yet.', 'How tested is it?', 'evidence-meter', '<h2>For specialists</h2>'):
            self.assertIn(part, text)

    def test_record_without_plain_text_renders_meter_and_share_row_only(self):
        text = self.page({'records': {}})
        self.assertIn('<section class="plain-short" aria-labelledby="plain-short-h"><h2 id="plain-short-h">How tested is it?</h2>', text)
        self.assertEqual(text.count('How tested is it?'), 1)
        self.assertNotIn('The short version', text)
        self.assertIn('Share on X', text)
        for part in ('In plain words', 'Why it matters', 'For specialists'):
            self.assertNotIn(part, text)

    def test_share_links_carry_the_encoded_canonical_url(self):
        text = self.page({}, has_image=True)
        url = 'https%3A%2F%2Faisciencetracker.org%2Fshare%2Fplain-a.html'
        self.assertIn(f'href="https://x.com/intent/post?text=Title%20A%20%26%20%3Cb%3E&amp;url={url}" target="_blank" rel="noopener"', text)
        self.assertIn(f'href="https://www.linkedin.com/sharing/share-offsite/?url={url}" target="_blank" rel="noopener"', text)
        self.assertIn('href="../og/plain-a.png" download', text)
        (self.g.ROOT / 'og/plain-a.png').unlink()
        self.assertNotIn('Download image', self.page({}))

    def test_structural_errors_are_rejected_before_any_output(self):
        for plain in ({'home': ['nope', 3]}, {'landmarks': 'nope'},
                      {'records': {'plain-a': dict(REC, plain='x' * 241)}},
                      {'records': {'plain-a': dict(REC, headline='x' * 91)}},
                      {'records': {'plain-a': {k: v for k, v in REC.items() if k != 'why'}}},
                      {'records': {'plain-a': {k: v for k, v in REC.items() if k != 'source'}}},
                      {'records': {'plain-a': dict(REC, extra='')}}):
            with self.assertRaises(ValueError):
                self.g.validate_plain(plain)
        self.g.validate_plain({'home': ['plain-a'], 'landmarks': [], 'records': {'plain-a': REC}})
        self.assertFalse((self.g.ROOT / 'share').exists())

    def test_unknown_or_outdated_records_are_skipped_with_a_warning(self):
        plain = {'home': ['plain-a', 'plain-b', 'gone'], 'landmarks': ['gone', 'plain-b'], 'records': {
            'plain-a': self.rec, 'gone': REC, 'plain-b': dict(REC, source=self.g.plain_source(self.b))}}
        changed = dict(self.b, summary='A different summary.')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            layer = self.g.usable_plain(plain, [self.a, changed])
        self.assertEqual(set(layer['records']), {'plain-a'})
        self.assertEqual((layer['home'], layer['landmarks']), (['plain-a'], []))
        self.assertEqual(len(err.getvalue().strip().splitlines()), 2)
        self.assertEqual(self.g.plain_home_html([self.a, changed], layer).count('class="plain-card"'), 1)
        self.g.write_discovery_pages([changed], {'families': []}, False, plain=layer)  # still renders
        self.assertNotIn('The short version', (self.g.ROOT / 'share/plain-b.html').read_text())

    def test_stamp_plain_writes_values_that_validate(self):
        (self.g.ROOT / 'data').mkdir()
        (self.g.ROOT / 'data/discoveries.json').write_text(json.dumps([self.a]))
        (self.g.ROOT / 'data/plain-language.json').write_text(json.dumps({'home': [], 'landmarks': [], 'records': {'plain-a': REC}}))
        argv, sys.argv = sys.argv, ['generate_share.py', '--stamp-plain']
        self.addCleanup(setattr, sys, 'argv', argv)
        self.g.main()
        plain = self.g.load_plain()
        self.g.validate_plain(plain)
        self.assertEqual(plain['records']['plain-a']['source'], self.g.plain_source(self.a))
        self.assertEqual(set(self.g.usable_plain(plain, [self.a])['records']), {'plain-a'})

    def test_missing_file_means_no_plain_texts(self):
        self.assertEqual(self.g.load_plain()['records'], {})

    def test_home_block_keeps_order_skips_incomplete_and_escapes(self):
        plain = {'home': ['plain-b', 'plain-a', 'plain-c'], 'records': {
            'plain-a': REC, 'plain-b': dict(REC, headline='Second'), 'plain-c': dict(REC, plain='')}}
        out = self.g.plain_home_html([self.a, self.b], plain)
        self.assertLess(out.index('share/plain-b.html'), out.index('share/plain-a.html'))
        self.assertNotIn('share/plain-c', out)
        self.assertIn('A &lt;short&gt; headline', out)
        self.assertIn('Plain &amp; simple.', out)
        self.assertIn('Start here', out)
        self.assertIn('href="insights.html"', out)
        self.assertEqual(out.count('class="plain-card"'), 2)



class LocaleLinkTests(unittest.TestCase):
    def test_language_editions_link_to_the_english_insights_page(self):
        root = Path(__file__).resolve().parents[1]
        for lang in ('it', 'de', 'fr', 'es'):
            for page in ('index.html', 'models.html'):
                text = (root / lang / page).read_text()
                self.assertIn('href="../insights.html"', text, f'{lang}/{page}')
                self.assertNotIn('href="insights.html"', text, f'{lang}/{page}')


if __name__ == '__main__':
    unittest.main()
