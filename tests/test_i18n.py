"""Language catalogs, first-visit detection and static page translation."""
import json
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
if (go({ua:'Mozilla/5.0 (compatible; Googlebot/2.1)', languages:['it-IT','it']}) !== null) throw new Error('bot');
if (go({languages:['it-IT','it','en']}) !== '/it/') throw new Error('italian');
if (go({path:'/', languages:['de-CH','fr']}) !== '/de/') throw new Error('de-CH');
if (go({path:'/index.html', search:'?q=1', hash:'#elenco', languages:['fr-CH']}) !== '/fr/?q=1#elenco') throw new Error('home query');
if (go({path:'/models.html', languages:['es']}) !== '/es/models.html') throw new Error('models');
if (go({ua:'Mozilla/5.0 (compatible; GoogleOther)', languages:['it-IT']}) !== null) throw new Error('googleother');
if (go({saved:'en', languages:['it-IT']}) !== null) throw new Error('saved english');
if (go({saved:'de', languages:['en']}) !== '/de/') throw new Error('saved german');
if (go({path:'/share/halicin.html', languages:['it']}) !== null) throw new Error('share');
if (go({path:'/it/methodology.html', languages:['de']}) !== null) throw new Error('already local');
if (go({languages:['zh-CN'], timezone:'Europe/Rome'}) !== '/it/') throw new Error('timezone');
if (go({languages:['en-CH'], timezone:'Europe/Zurich'}) !== null) throw new Error('en-CH');
if (go({languages:['en-GB'], timezone:'Europe/Rome'}) !== null) throw new Error('english wins');
const home = astEquivalent('fr', '/methodology.html', '?q=1', '#elenco', pages);
if (home !== '/fr/methodology.html?q=1#elenco') throw new Error('switch '+home);
const back = astEquivalent('en', '/de/security.html', '', '', pages);
if (back !== '/security.html') throw new Error('back '+back);
const share = astEquivalent('it', '/share/2020-02-halicin.html', '', '', pages);
if (share !== '/it/#discovery=2020-02-halicin') throw new Error('entry '+share);
const root = astEquivalent('es', '/index.html', '', '#discovery=x', pages);
if (root !== '/es/#discovery=x') throw new Error('root '+root);
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
        self.assertIn('<link rel="canonical" href="https://aisciencetracker.org/">', page)
        self.assertIn('<meta property="og:url" content="https://aisciencetracker.org/">', page)
        self.assertIn('<link rel="alternate" hreflang="it" href="https://aisciencetracker.org/it/">', page)
        self.assertIn('<link rel="alternate" hreflang="x-default" href="https://aisciencetracker.org/">', page)
        self.assertNotIn('https://aisciencetracker.org/index.html"', page)
        italian = (ROOT / 'it' / 'index.html').read_text()
        self.assertIn('<link rel="canonical" href="https://aisciencetracker.org/it/">', italian)
        self.assertIn('<meta property="og:url" content="https://aisciencetracker.org/it/">', italian)
        self.assertIn('hreflang="de" href="https://aisciencetracker.org/de/"', italian)
        self.assertNotIn('"@type":"Dataset"', (ROOT / 'methodology.html').read_text())
        self.assertIn('"@type":"Dataset"', page)
        english = json.loads((MESSAGES / 'en.json').read_text())
        self.assertIn('{n} of {total} discoveries', english)


if __name__ == '__main__':
    unittest.main()
