"""Language catalogs, first-visit detection and static page translation."""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / 'scripts'))
from i18n_site import (DETECT_FN, LOCALES, PAGES, catalog_errors, load_json, translate_document,
                       keep_english, MESSAGES)


class LanguageCatalogTests(unittest.TestCase):
    def test_every_locale_covers_the_english_catalog(self):
        errors = catalog_errors(ROOT)
        self.assertEqual(errors, [], '\n'.join(errors[:12]))

    def test_discovery_overlays_are_objects_keyed_by_id(self):
        for lang in LOCALES:
            data = load_json(ROOT / 'i18n' / 'discoveries' / f'{lang}.json')
            self.assertIsInstance(data, dict)
            for entry_id, row in data.items():
                self.assertIsInstance(row.get('summary'), str, entry_id)

    def test_detection_respects_bots_saved_choice_and_browser_language(self):
        script = DETECT_FN + """
const pages = """ + json.dumps(list(PAGES)) + """;
const go = (extra) => astResolveLanguage(Object.assign({pages, path:'/index.html', search:'', hash:'', saved:'', languages:['en'], timezone:'', ua:'Mozilla/5.0'}, extra));
if (go({ua:'Mozilla/5.0 (compatible; Googlebot/2.1)', languages:['it-IT','it']}) !== '/') throw new Error('bot cleans home');
if (go({ua:'Mozilla/5.0 (compatible; GoogleOther)', languages:['it-IT']}) !== '/') throw new Error('googleother cleans home');
if (go({ua:'Mozilla/5.0 (compatible; Googlebot/2.1)', path:'/methodology.html', languages:['it']}) !== null) throw new Error('bot stays');
if (go({languages:['it-IT','it','en']}) !== '/it/') throw new Error('italian');
if (go({path:'/', languages:['de-CH','fr']}) !== '/de/') throw new Error('de-CH');
if (go({path:'/index.html', search:'?q=1', hash:'#elenco', languages:['fr-CH']}) !== '/fr/?q=1#elenco') throw new Error('home query');
if (go({path:'/models.html', languages:['es']}) !== '/es/models.html') throw new Error('models');
if (go({saved:'en', languages:['it-IT']}) !== '/') throw new Error('saved english cleans index');
if (go({saved:'en', path:'/', languages:['it-IT']}) !== null) throw new Error('clean english stays');
if (go({saved:'de', languages:['en']}) !== '/de/') throw new Error('saved german');
if (go({path:'/share/halicin.html', languages:['it']}) !== null) throw new Error('share');
if (go({path:'/it/methodology.html', languages:['de']}) !== null) throw new Error('already local');
if (go({path:'/it/index.html', languages:['de']}) !== '/it/') throw new Error('locale home cleaned');
if (go({languages:['zh-CN'], timezone:'Europe/Rome'}) !== '/it/') throw new Error('timezone');
if (go({languages:['en-CH'], timezone:'Europe/Zurich'}) !== '/') throw new Error('en-CH cleans dirty home');
if (go({languages:['en-GB'], timezone:'Europe/Rome'}) !== '/') throw new Error('english cleans dirty home');
if (go({path:'/', languages:['en-GB'], timezone:'Europe/Rome'}) !== null) throw new Error('english wins');
const home = astEquivalent('fr', '/methodology.html', '?q=1', '#elenco', pages);
if (home !== '/fr/methodology.html?q=1#elenco') throw new Error('switch '+home);
const back = astEquivalent('en', '/de/security.html', '', '', pages);
if (back !== '/security.html') throw new Error('back '+back);
const share = astEquivalent('it', '/share/2020-02-halicin.html', '', '', pages);
if (share !== '/it/#discovery=2020-02-halicin') throw new Error('entry '+share);
const root = astEquivalent('es', '/index.html', '', '#discovery=x', pages);
if (root !== '/es/#discovery=x') throw new Error('root '+root);
const englishHome = astEquivalent('en', '/index.html', '', '#elenco', pages);
if (englishHome !== '/#elenco') throw new Error('english home '+englishHome);
"""
        result = subprocess.run(['node', '-e', script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_translation_keeps_titles_and_uses_locale_copy(self):
        page = """<!doctype html><html lang="en"><head><title>Hello</title>
<meta name="description" content="A short description of the catalog."></head>
<body><header><nav class="menu" aria-label="Site sections"><a href="index.html">Discoveries</a></nav>
<nav class="menu" id="lang-switch" data-i18n-skip><a data-lang="en">EN</a></nav></header>
<p>Hello world</p>
<ul><li><a href="share/example.html">Original title stays</a>. A learned model selected a compound.</li></ul>
</body></html>"""
        table = {
            'Hello': 'Ciao',
            'Hello world': 'Ciao mondo',
            'A short description of the catalog.': 'Una breve descrizione del catalogo.',
            'Discoveries': 'Scoperte',
            'Site sections': 'Sezioni',
            '⟦*⟧. A learned model selected a compound.': '⟦*⟧. Un modello appreso ha selezionato un composto.',
        }
        # The locked share link makes the list item key include ⟦*⟧.
        out, missing = translate_document(page, table, keep_english())
        self.assertEqual(missing, [])
        self.assertIn('>Ciao<', out)
        self.assertIn('Una breve descrizione del catalogo.', out)
        self.assertIn('>Scoperte<', out)
        self.assertIn('Original title stays', out)
        self.assertIn('Un modello appreso ha selezionato un composto.', out)
        self.assertIn('>EN<', out)

    def test_english_pages_keep_detection_switcher_and_policy(self):
        page = (ROOT / 'index.html').read_text()
        self.assertIn('lang="en"', page)
        self.assertIn('id="lang-switch"', page)
        self.assertIn('hreflang="x-default"', page)
        self.assertIn("default-src 'self'", page)
        self.assertIn('ast-lang', page)
        self.assertIn('https://static.cloudflareinsights.com/beacon.min.js', page)
        self.assertIn('storageOk', page)
        self.assertIn('rel="canonical" href="https://aisciencetracker.org/"', page)
        self.assertIn('<meta property="og:url" content="https://aisciencetracker.org/">', page)
        self.assertIn('<link rel="alternate" hreflang="it" href="https://aisciencetracker.org/it/">', page)
        self.assertIn('<link rel="alternate" hreflang="x-default" href="https://aisciencetracker.org/">', page)
        self.assertNotIn('https://aisciencetracker.org/index.html', page)
        self.assertIn('https://iamops.dev/', page)
        self.assertNotIn('"@type":"Dataset"', page)
        self.assertNotIn('"@type":"Dataset"', (ROOT / 'methodology.html').read_text())
        self.assertIn('dataset.html#scientific-dataset', (ROOT / 'dataset.html').read_text())
        italian = (ROOT / 'it' / 'index.html').read_text()
        self.assertIn('<link rel="canonical" href="https://aisciencetracker.org/it/">', italian)
        self.assertIn('https://iamops.dev/it/', italian)
        english = json.loads((MESSAGES / 'en.json').read_text())
        self.assertIn('{n} of {total} discoveries', english)

    def test_home_uses_the_compact_header_and_generated_pulse(self):
        page = (ROOT / 'index.html').read_text()
        self.assertIn('id="lang-details"', page)
        self.assertIn('class="nav-toggle"', page)
        self.assertIn('>Vulnerabilities</a>', page)
        self.assertIn('class="hero-live"', page)
        self.assertIn('data-i18n-skip', page)
        self.assertNotIn('id="explore-overview"', page)
        self.assertIn('Chart heights show coarse editorial relevance, not scientific quality.', page)
        lead = page.split('id="lead">', 1)[1].split('</p>', 1)[0]
        self.assertNotIn('Chart heights', lead)

    def test_linkedin_company_profile_is_on_every_edition(self):
        url = 'https://www.linkedin.com/company/aisciencetracker/'
        link = f'<a href="{url}" rel="me noopener">LinkedIn</a>'
        same_as = ('"sameAs":["https://github.com/marcello-pichini/ai-science-tracker",'
                   '"https://doi.org/10.5281/zenodo.24217686",'
                   '"https://huggingface.co/datasets/marcello-pichini/ai-science-tracker",'
                   f'"{url}"]')
        footers = [ROOT / page for page in PAGES]
        footers += [ROOT / 'materials-dossier.html', ROOT / 'mathematics-dossier.html']
        for lang in LOCALES:
            footers += [ROOT / lang / page for page in PAGES]
        footers += [next((ROOT / 'share').glob('*.html')), ROOT / 'profiles' / 'index.html']
        for path in footers:
            text = path.read_text(encoding='utf-8')
            with self.subTest(page=str(path.relative_to(ROOT))):
                self.assertIn(link, text)
                self.assertNotIn('target="_blank"', text[text.find('<footer'):text.find('</footer>')])
                csp = re.search(r'Content-Security-Policy" content="([^"]+)"', text)
                self.assertIsNotNone(csp)
                self.assertNotIn('linkedin', csp.group(1))
                self.assertIn("default-src 'self'", csp.group(1))
        for path in (ROOT / 'index.html', ROOT / 'it' / 'index.html', ROOT / 'profiles' / 'index.html', next((ROOT / 'share').glob('*.html'))):
            text = path.read_text(encoding='utf-8')
            with self.subTest(sameAs=str(path.relative_to(ROOT))):
                self.assertIn(same_as, text)


if __name__ == '__main__':
    unittest.main()
