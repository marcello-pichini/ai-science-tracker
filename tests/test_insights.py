import html
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import generate_insights as gi  # noqa: E402
import generate_share as gs  # noqa: E402

SLUGS = ['labs', 'landmarks', 'topics', 'who', 'kind-of-ai', 'which-models', 'by-year']


def record(i, year, field='medicine', test_type='direct test', status='Peer-reviewed paper', org='Stanford University',
           tech='XGBoost model', title='A cancer study', added='2026-11-20'):
    return {'id': f'{year}-r{i}', 'title': title, 'summary': 'Finds new targets.', 'field': field, 'organization': org,
            'ai_technology': tech, 'publication_date': f'{year}-05-01', 'added_date': added,
            'evidence': {'test_type': test_type, 'publication_status': status}}


ITEMS = [
    record(1, 2024, test_type='retrospective or benchmark'),
    record(2, 2025, test_type='prospective or independent check', org='Stanford University; Not stated in the abstract'),
    record(3, 2026, field='mathematics', tech='A large language model proof', status='Preprint', title='A theorem', added='2026-11-25'),
    record(4, 2026, test_type='replication or operational use', status='Announcement'),
    record(5, 2026, test_type=None, org='MIT'),
]
MODELS = {'families': [{'id': 'claude', 'name': 'Claude', 'discoveries': ['2026-r3', '2026-r4']},
                       {'id': 'gpt4', 'name': 'GPT-4', 'discoveries': ['2024-r1']},
                       {'id': 'esm', 'name': 'ESM', 'discoveries': ['2025-r2']},
                       {'id': 'gpt5', 'name': 'GPT-5', 'discoveries': ['2024-r1', '2026-r3', 'not-in-catalog']},
                       {'id': 'nolab', 'name': 'No lab', 'discoveries': ['2026-r5']}],
          'models': [{'family': 'claude', 'date': '2024-03-04', 'organization': 'Anthropic'},
                     {'family': 'esm', 'date': '2022-01-01', 'organization': 'Meta AI,Stanford University'},
                     {'family': 'gpt4', 'organization': 'OpenAI'}, {'family': 'gpt5', 'organization': 'OpenAI'}]}
PLAIN = {'landmarks': ['2024-r1', 'missing-id', '2026-r3', '2025-r2'],
         'records': {'2024-r1': {'headline': 'First headline'}, '2026-r3': {'headline': 'Third headline'},
                     '2025-r2': {'headline': ''}}}


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir()
        shutil.copyfile(ROOT / 'styles.css', self.root / 'styles.css')
        (self.root / 'index.html').write_text('<header class="header"><nav class="menu"><a href="security.html" aria-current="page">Security</a></nav></header><footer class="footer"><a href="guide.html">Guide</a></footer>')
        original = gs.ROOT
        gs.ROOT = self.root
        self.addCleanup(setattr, gs, 'ROOT', original)

    def page(self, items=ITEMS, models=MODELS, plain=PLAIN):
        gi.write_insights(items, models, plain, root=self.root)
        return (self.root / 'insights.html').read_text(encoding='utf-8')

    def test_seven_sections_in_order_and_one_h1(self):
        text = self.page()
        self.assertEqual(re.findall(r'<section class="sez" id="([^"]+)"', text), SLUGS)
        self.assertEqual(text.count('<h1'), 1)
        self.assertEqual(text.count('<h2'), 8)  # seven charts and the reuse section
        self.assertEqual(text.count('View data as a table'), 7)
        self.assertEqual(text.count('<table'), 7 + 3)  # seven data tables, heat grid and two matrices
        self.assertNotIn('../', text.split('<body', 1)[1])

    def test_headline_numbers_match_independent_counts(self):
        text = self.page()
        n = len(ITEMS)
        tested = sum(1 for d in ITEMS if d['evidence']['test_type'] in ('direct test', 'prospective or independent check', 'replication or operational use'))
        independent = sum(1 for d in ITEMS if d['evidence']['test_type'] in ('prospective or independent check', 'replication or operational use'))
        facts = re.findall(r'<dd>(.*?)</dd>', re.search(r'<dl class="collection-facts insight-facts">.*?</dl>', text, re.S).group(0))
        self.assertEqual([re.sub(r'<[^>]+>', '', f).split() for f in facts],
                         [[str(n)], [f'{round(tested * 100 / n)}%', str(tested)], [f'{round(independent * 100 / n)}%', str(independent)]])
        self.assertIn('Stanford University</b><span>4 entries', text)
        self.assertIn('2024: 1 peer-reviewed, 0 preprints, 0 other', html.unescape(text))
        self.assertIn('2026: 1 peer-reviewed, 1 preprints, 1 other', html.unescape(text))
        self.assertIn('as of 25 Nov 2026', text)
        self.assertIn('Cancer: 4 entries', html.unescape(text))

    def test_landmarks_skip_missing_ids_and_empty_headlines(self):
        text = self.page()
        block = re.search(r'<ol class="insight-timeline">.*?</ol>', text, re.S).group(0)
        self.assertEqual(re.findall(r'href="(share/[^"]+)"', block), ['share/2024-r1.html', 'share/2026-r3.html'])
        self.assertIn('2 landmark results and claims in AI-enabled science, from 2024 to 2026', text)
        self.assertIn('evidence-meter', block)

    def test_models_skip_families_without_a_dated_release(self):
        text = self.page()
        matrix = re.search(r'<table class="insight-matrix">.*?</table>', text, re.S).group(0)
        self.assertIn('Claude', matrix)
        self.assertIn('ESM', matrix)
        self.assertNotIn('GPT-4', matrix)  # listed family with no dated release

    def test_lab_totals_count_unique_entries_and_leave_out_families_without_a_lab(self):
        text = self.page()
        block = re.search(r'<table class="insight-matrix insight-matrix-wide">.*?</table>', text, re.S).group(0)
        totals = dict(re.findall(r'<th scope="row">([^<]+)</th>.*?<td class="insight-total">(\d+)</td>', block))
        by_family = {f['id']: {d for d in f['discoveries'] if d in {r['id'] for r in ITEMS}} for f in MODELS['families']}
        expected = {'OpenAI': by_family['gpt4'] | by_family['gpt5'], 'Anthropic': by_family['claude'], 'Meta': by_family['esm']}
        self.assertEqual(totals, {k: str(len(v)) for k, v in expected.items()})
        self.assertEqual(totals['OpenAI'], '2')  # 2024-r1 is linked to two OpenAI families and counts once
        self.assertNotIn('No lab', block)
        self.assertIn('Anthropic and OpenAI are linked to the most entries (2 each); Meta follows with 1', text)
        self.assertIn('Left out: 1 entry linked to a model family with no lab.', text)
        self.assertIn('not that the lab made the discovery', text)

    def lab_totals(self, models):
        block = re.search(r'<table class="insight-matrix insight-matrix-wide">.*?</table>', self.page(models=models), re.S).group(0)
        return dict(re.findall(r'<th scope="row">([^<]+)</th>.*?<td class="insight-total">(\d+)</td>', block))

    def test_family_lab_map_fills_only_families_without_a_lab(self):
        base = dict(MODELS, families=MODELS['families'] + [{'id': 'aurora', 'name': 'Aurora', 'discoveries': ['2025-r2']}])
        self.assertEqual(self.lab_totals(base)['Microsoft'], '1')  # no model rows, counted under the mapped lab
        self.assertIn('Left out: 1 entry linked', self.page(models=base))  # 'nolab' is unmapped and still disclosed
        owned = dict(base, models=base['models'] + [{'family': 'aurora', 'organization': 'OpenAI'}])
        totals = self.lab_totals(owned)
        self.assertNotIn('Microsoft', totals)  # models.json wins over the map
        self.assertEqual(totals['OpenAI'], '3')

    def test_family_lab_map_entries_exist_and_have_no_lab_in_the_data(self):
        data = json.loads((ROOT / 'data/models.json').read_text())
        with_lab = {m['family'] for m in data['models'] if m.get('family') and gi.lab_for(m.get('organization') or '')}
        ids = {f['id'] for f in data['families']}
        for fid in gi.FAMILY_LAB:
            self.assertIn(fid, ids)
            self.assertNotIn(fid, with_lab)

    def test_by_year_growth_figure_and_fallback(self):
        peer = [(2020, 1), (2021, 2), (2022, 4), (2023, 8), (2024, 5)]
        items = [record(f'{y}-{i}', y) for y, n in peer for i in range(n)]
        text = self.page(items, MODELS, PLAIN)
        self.assertIn('Peer-reviewed entries in the catalog grew 5.0-fold from 2020 to 2024, about 50% a year', text)  # 5 ** (1 / 4) - 1
        self.assertIn('incomplete', text)
        self.assertNotIn('exponential', text)
        fallback = self.page()  # only two years before the collection change
        self.assertIn('Catalog entries by publication year, 2024 to 2026', fallback)
        self.assertNotIn('exponential', fallback)

    def by_year_title(self, text):
        return re.search(r'<h2 id="by-year-t">(.*?)</h2>', text).group(1)

    def models_title(self, text):
        return re.search(r'<h2 id="which-models-t">(.*?)</h2>', text).group(1)

    def test_a_new_year_does_not_change_the_year_titles(self):
        peer = [(2020, 1), (2021, 2), (2022, 4), (2023, 8), (2024, 5), (2025, 6), (2026, 6)]
        items = [record(f'{y}-{i}', y) for y, n in peer for i in range(n)]
        families = {'families': [{'id': 'claude', 'name': 'Claude', 'discoveries': [d['id'] for d in items if d['id'].startswith('2026')]}],
                    'models': [{'family': 'claude', 'date': '2024-03-04', 'organization': 'Anthropic'}]}
        before = self.page(items, families, PLAIN)
        january = dict(record('jan', 2027, added='2027-01-05'), id='2027-jan')
        after = self.page(items + [january], families, PLAIN)
        self.assertIn('grew 6.0-fold from 2020 to 2025', self.by_year_title(before))
        self.assertEqual(self.by_year_title(before), self.by_year_title(after))
        self.assertEqual(re.findall(r'class="insight-col is-latest"><div class="insight-col-area"><em>wider collection</em><b>(\d+)', after), ['6'])
        expected = 'In 2026, 6 entries are linked to general-purpose assistants and 0 to models built for science'
        self.assertEqual(self.models_title(before), expected)
        self.assertEqual(self.models_title(after), expected)  # 2027 has 1 entry, under half of 6

    def test_models_title_falls_back_when_nothing_is_linked(self):
        self.assertEqual(self.models_title(self.page([record(1, 2026)], {}, PLAIN)), 'Entries linked to model families, by year')

    def test_cells_and_headlines_are_always_escaped(self):
        evil = '<img src=x onerror=alert(1)>'
        items = [dict(record(1, 2024), organization=evil), dict(record(2, 2025), id='2025-r2')]
        plain = {'landmarks': ['2024-r1'], 'records': {'2024-r1': {'headline': '<script>alert(2)</script>'}}}
        text = self.page(items, MODELS, plain)
        self.assertNotIn('<img src=x', text)
        self.assertNotIn('<script>alert', text)
        self.assertIn('&lt;script&gt;alert(2)', text)

    def test_proof_of_concept_is_not_mathematics(self):
        items = [dict(record(1, 2024), title='A proof-of-concept classifier', summary='A proof of concept for screening.'),
                 dict(record(2, 2025), title='A lemma', summary='Finds a theorem.')]
        text = html.unescape(self.page(items, MODELS, PLAIN))
        self.assertIn('<th scope="row">Mathematics</th><td>1</td>', text)

    def test_institution_kinds(self):
        for name, kind in [('Stanford University', 'University'), ('Mayo Clinic', 'Research institution'),
                           ('Google DeepMind', 'AI lab or company'), ('Chinese Academy of Sciences', 'Research academy'),
                           ('ETH Zurich', 'University')]:
            self.assertEqual(gi.organization_kind(name), kind)

    def test_empty_input_does_not_crash(self):
        text = self.page([], {}, {})
        self.assertEqual(re.findall(r'<section class="sez" id="([^"]+)"', text), SLUGS)
        self.assertEqual(text.count('<h1'), 1)
        self.assertIn('data as of not available', text)
        self.assertIn('0%', text)

    def test_title_and_description_fit_search_snippets(self):
        text = self.page()
        title = html.unescape(re.search(r'<title>(.*?)</title>', text).group(1))
        desc = html.unescape(re.search(r'<meta name="description" content="([^"]*)"', text).group(1))
        self.assertLessEqual(len(title), 60)
        self.assertTrue(title.endswith('AI Science Tracker'))
        self.assertTrue(110 <= len(desc) <= 160, len(desc))
        self.assertIn('rel="canonical" href="https://aisciencetracker.org/insights.html"', text)
        self.assertNotIn('noindex', text)
        self.assertIn('"@type":"WebPage"', text)
        self.assertIn('"@type":"BreadcrumbList"', text)
        self.assertIn('og:image" content="https://aisciencetracker.org/og/default.png"', text)

    def test_share_links_carry_the_encoded_page_url_and_slug(self):
        text = self.page()
        for slug in SLUGS:
            url = f'https://aisciencetracker.org/insights.html#{slug}'
            section = re.search(rf'<section class="sez" id="{slug}".*?</section>', text, re.S).group(0)
            self.assertIn(f'https://www.linkedin.com/sharing/share-offsite/?url={quote(url, safe="")}', section)
            self.assertIn(f'&amp;url={quote(url, safe="")}', section)
            self.assertEqual(section.count('target="_blank" rel="noopener"'), 2)
            self.assertIn('Share on X</a>', section)
            self.assertIn('Share on LinkedIn</a>', section)

    def test_page_has_no_style_script_or_literal_colors_of_its_own(self):
        text = self.page()
        body = text.split('<body', 1)[1]
        main = body.split('<main>', 1)[1].split('</main>', 1)[0]
        self.assertNotIn('<style', text)
        self.assertNotIn('<script', body)
        self.assertNotRegex(main, r'#[0-9a-fA-F]{3,8}\b|rgba?\(')
        self.assertNotRegex(main, r'style="(?!--[a-z]+:[-0-9.]+"|flex:\d+"|--h:[0-9.]+"|--n:\d+")')
        self.assertRegex(text, r'href="styles.css\?v=[a-f0-9]{12}"')

    def test_stylesheet_region_has_no_literal_colors(self):
        css = (ROOT / 'styles.css').read_text(encoding='utf-8')
        region = css.split('/* insights:start */', 1)[1].split('/* insights:end */', 1)[0]
        self.assertIn('.insight-card', region)
        self.assertNotRegex(region, r'#[0-9a-fA-F]{3,8}\b|rgba?\(')

    def test_output_is_identical_on_a_second_run(self):
        self.assertEqual(self.page(), self.page())


if __name__ == '__main__':
    unittest.main()
