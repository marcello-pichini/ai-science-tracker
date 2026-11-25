#!/usr/bin/env python3
"""Static language editions for the editorial pages.

English files at the site root stay canonical. This module writes /it/, /de/,
/fr/ and /es/ from those files and from i18n/messages/<lang>.json. Discovery
summaries are an optional overlay in i18n/discoveries/<lang>.json; a missing
summary stays in English. Titles, paper names and source links are never
translated.

    python3 scripts/i18n_site.py            # refresh locale pages
    python3 scripts/i18n_site.py --check    # fail if a catalog key is missing
    python3 scripts/i18n_site.py --sync-en  # add newly found English keys
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://aisciencetracker.org/'
MESSAGES = ROOT / 'i18n' / 'messages'
DOSSIER_MESSAGES = ROOT / 'i18n' / 'dossiers.json'
DISCOVERIES = ROOT / 'i18n' / 'discoveries'
KEEP_PATH = ROOT / 'i18n' / 'keep-english.txt'

LOCALES = ('it', 'de', 'fr', 'es')
LOCALE_META = {
    'en': {'html': 'en', 'og': 'en_GB', 'intl': 'en-GB', 'label': 'EN', 'name': 'English'},
    'it': {'html': 'it', 'og': 'it_IT', 'intl': 'it-IT', 'label': 'IT', 'name': 'Italiano'},
    'de': {'html': 'de', 'og': 'de_DE', 'intl': 'de-DE', 'label': 'DE', 'name': 'Deutsch'},
    'fr': {'html': 'fr', 'og': 'fr_FR', 'intl': 'fr-FR', 'label': 'FR', 'name': 'Français'},
    'es': {'html': 'es', 'og': 'es_ES', 'intl': 'es-ES', 'label': 'ES', 'name': 'Español'},
}

# Shared language routes embedded in the existing site chrome.
SHARED_PAGES = (
    'index.html', 'models.html', 'security.html', 'dossiers.html', 'methodology.html',
    'guide.html', 'search.html', 'dataset.html', 'contributors.html', 'contact.html',
    'model-progress.html', 'profile.html', 'alphafold-dossier.html', 'antibiotic-dossier.html',
    '404.html',
)
NEW_DOSSIER_PAGES = (
    'materials-dossier.html', 'mathematics-dossier.html', 'seismology-dossier.html',
    'astronomy-dossier.html', 'floods-dossier.html', 'vulnerabilities-dossier.html',
    'model-releases-dossier.html',
)
PAGES = SHARED_PAGES + NEW_DOSSIER_PAGES
SITEMAP_PAGES = tuple(page for page in PAGES if page != '404.html')

ASSET_PREFIXES = ('assets/', 'data/', 'share/', 'profiles/', 'api/', 'og/', 'docs/', 'schema/')
# insights.html is generated in English only, so language editions link to the root copy.
ASSET_FILES = {'styles.css', 'feed.xml', 'sitemap.xml', 'llms.txt', 'robots.txt', 'insights.html'}
SKIP_TAGS = {'script', 'style'}
NUMBER = re.compile(r'\d+(?:\.\d+)?')
KEEP_LINE = re.compile(
    r'^(?:AI Science Tracker|CC BY(?:[-\w.]*)?(?: \d+(?:\.\d+)?)?|https?://\S+|10\.\d{4,9}/\S+)$'
)
TR_CALL = re.compile(r'''(?:\btr|\bthis\.t|\bAST_t)\(\s*(['"])(.*?)\1''', re.S)

DETECT_FN = r'''
globalThis.astCleanPath = function (path) {
  path = path || '/';
  if (path === '/index.html') return '/';
  var home = path.match(/^\/(it|de|fr|es)\/index\.html$/);
  if (home) return '/' + home[1] + '/';
  return path;
};
globalThis.astResolveLanguage = function (input) {
  var SUPPORTED = {it:1, de:1, fr:1, es:1};
  var ua = input.ua || '';
  var bot = /bot|crawl|spider|slurp|bingpreview|facebookexternalhit|embedly|quora|pinterest|redditbot|applebot|linkedinbot|whatsapp|telegrambot|googlebot|googleother|google-extended|google-inspectiontool|google-read-aloud|duplexweb|adsbot|mediapartners|baiduspider|yandex|duckduckbot|semrush|ahrefs|petalbot|bytespider|gptbot|claudebot|amazonbot|ccbot|ia_archiver|facebookcatalog/i.test(ua);
  var raw = input.path || '/';
  var path = astCleanPath(raw);
  var search = input.search || '';
  var hash = input.hash || '';
  var cleaned = path + search + hash;
  // Crawlers are not sent to another language. They are sent from /index.html to /.
  if (bot) return path === raw ? null : cleaned;
  if (/^\/(it|de|fr|es)(\/|$)/.test(path)) return path === raw ? null : cleaned;
  var pages = input.pages || [];
  var saved = input.saved || '';
  var target = (saved === 'en' || SUPPORTED[saved]) ? saved : '';
  if (!target) {
    var list = input.languages || [];
    for (var i = 0; i < list.length; i++) {
      var code = String(list[i] || '').toLowerCase().split('-')[0];
      if (code === 'en' || SUPPORTED[code]) { target = code; break; }
    }
  }
  if (!target) {
    var hint = {
      'Europe/Rome':'it','Europe/Vatican':'it','Europe/San_Marino':'it',
      'Europe/Berlin':'de','Europe/Busingen':'de','Europe/Vienna':'de',
      'Europe/Paris':'fr','Europe/Monaco':'fr',
      'Europe/Madrid':'es','Atlantic/Canary':'es','Africa/Ceuta':'es','Europe/Andorra':'es',
      'America/Mexico_City':'es','America/Argentina/Buenos_Aires':'es','America/Bogota':'es',
      'America/Lima':'es','America/Santiago':'es','America/Montevideo':'es','America/Asuncion':'es',
      'America/La_Paz':'es','America/Caracas':'es','America/Guayaquil':'es'
    };
    if (hint[input.timezone || '']) target = hint[input.timezone];
  }
  if (target && target !== 'en' && SUPPORTED[target]) {
    if (path === '/' || path === '') return '/' + target + '/' + search + hash;
    var file = path.split('/').pop();
    var dir = path.slice(0, path.length - file.length);
    if (dir !== '/') return path === raw ? null : cleaned;
    if (!file || file === 'index.html') return '/' + target + '/' + search + hash;
    if (pages.indexOf(file) < 0) return path === raw ? null : cleaned;
    return '/' + target + '/' + file + search + hash;
  }
  return path === raw ? null : cleaned;
};
globalThis.astEquivalent = function (lang, path, search, hash, pages) {
  search = search || '';
  hash = hash || '';
  pages = pages || [];
  var prefixed = String(path || '/').match(/^\/(it|de|fr|es)(?=\/|$)/);
  var rest = prefixed ? path.slice(prefixed[0].length) : (path || '/');
  if (rest === '' || rest === '/' || rest === '/index.html') rest = '/';
  var prefix = lang === 'en' ? '' : '/' + lang;
  if (rest === '/') return prefix + '/' + search + hash;
  var file = rest.split('/').pop();
  var dir = rest.slice(0, rest.length - file.length);
  if ((dir === '/' || dir === '') && file === 'index.html') return prefix + '/' + search + hash;
  if ((dir === '/' || dir === '') && pages.indexOf(file) >= 0) return prefix + '/' + file + search + hash;
  var share = rest.match(/^\/share\/([^/]+)\.html$/);
  if (share) return prefix + '/#discovery=' + share[1];
  if (file === 'profile.html') return prefix + '/profile.html' + search + hash;
  return prefix + '/' + search;
};
'''

DETECT_BLOCK = re.compile(
    r'(?:globalThis\.astCleanPath = function \(path\) \{\n.*?\n\};\n)?'
    r'globalThis\.astResolveLanguage = function \(input\) \{\n.*?\n\};\n'
    r'globalThis\.astEquivalent = function \(lang, path, search, hash, pages\) \{\n.*?\n\};\n',
    re.S)


def public_url(page: str, lang: str = 'en') -> str:
    """Absolute URL. The homepage is / and /it/, never /index.html."""
    if page == 'index.html':
        return BASE if lang == 'en' else f'{BASE}{lang}/'
    if lang == 'en':
        return BASE + page
    return f'{BASE}{lang}/{page}'


def home_href(lang: str) -> str:
    return '/' if lang == 'en' else f'/{lang}/'


# iamops.dev publishes the same five languages. Each edition links to its match.
IAMOPS_URL = {
    'en': 'https://iamops.dev/',
    'it': 'https://iamops.dev/it/',
    'de': 'https://iamops.dev/de/',
    'fr': 'https://iamops.dev/fr/',
    'es': 'https://iamops.dev/es/',
}
SEE_ALSO = '<p>See also: <a href="https://iamops.dev/">iamops.dev: IAM, AI agents and DevOps notes</a></p>'


def retarget_iamops(text: str, lang: str) -> str:
    """Point the footer link at the iamops.dev edition for this language."""
    return text.replace('href="https://iamops.dev/"', f'href="{IAMOPS_URL[lang]}"', 1)


def rewrite_dirty_homes(text: str) -> str:
    """Replace declared /index.html URLs with the directory URL GitHub Pages already serves."""
    for code in LOCALES:
        text = text.replace(f'{BASE}{code}/index.html', f'{BASE}{code}/')
    text = text.replace(BASE + 'index.html', BASE)
    return text


def clean_home_links(text: str, home: str) -> str:
    """Point in-page home links at / or /it/. The language switcher keeps its own targets."""
    def rewrite(chunk: str) -> str:
        chunk = re.sub(
            r'(href|action)="index\.html(#[^"]*)?"',
            lambda match: f'{match.group(1)}="{home}{match.group(2) or ""}"',
            chunk)
        # Root-absolute home links (/ and /#hash) follow the page language.
        # /models.html and https:// URLs do not match.
        return re.sub(
            r'(href|action)="/(#[^"]*)?"',
            lambda match: f'{match.group(1)}="{home}{match.group(2) or ""}"',
            chunk)

    parts = re.split(r'(<nav class="menu" id="lang-switch".*?</nav>)', text, flags=re.S)
    return ''.join(part if part.startswith('<nav class="menu" id="lang-switch"') else rewrite(part) for part in parts)


def set_switcher_hrefs(text: str, page: str = 'index.html') -> str:
    def repl(match: re.Match) -> str:
        block = match.group(0)
        for code in ('en',) + LOCALES:
            href = home_href(code) + (page if page in NEW_DOSSIER_PAGES else '')
            block = re.sub(
                rf'href="[^"]*"(\s[^>]*\bdata-lang="{code}")',
                f'href="{href}"\\1', block, count=1)
        return block
    return re.sub(r'<nav class="menu" id="lang-switch".*?</nav>', repl, text, count=1, flags=re.S)


def ensure_twitter(text: str) -> str:
    if 'name="twitter:title"' in text:
        return text
    title = re.search(r'<meta property="og:title" content="([^"]*)"', text)
    if not title:
        return text
    tags = f'<meta name="twitter:title" content="{title.group(1)}">\n'
    desc = re.search(r'<meta property="og:description" content="([^"]*)"', text)
    if desc:
        tags += f'<meta name="twitter:description" content="{desc.group(1)}">\n'
    return text.replace('<meta name="twitter:card"', tags + '<meta name="twitter:card"', 1)


def refresh_detection(text: str) -> str:
    updated, count = DETECT_BLOCK.subn(DETECT_FN.strip() + '\n', text)
    if count == 0 and 'function astCleanPath' not in text and 'astResolveLanguage' in text:
        raise RuntimeError('language detection script could not be refreshed')
    return updated


GLOBE_SVG = (
    '<svg class="globe" viewBox="0 0 24 24" aria-hidden="true">'
    '<circle cx="12" cy="12" r="8.25" fill="none" stroke="currentColor" stroke-width="1.6"/>'
    '<path d="M12 3.75c2.2 2.4 3.3 5.2 3.3 8.25s-1.1 5.85-3.3 8.25c-2.2-2.4-3.3-5.2-3.3-8.25s1.1-5.85 3.3-8.25z" '
    'fill="none" stroke="currentColor" stroke-width="1.6"/>'
    '<path d="M4.2 12h15.6M5.4 8.25h13.2M5.4 15.75h13.2" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round"/>'
    '</svg>'
)
NAV_TOGGLE = (
    '<button type="button" class="nav-toggle" aria-expanded="false" aria-controls="site-nav" aria-label="Open menu">'
    '<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M5 7h14M5 12h14M5 17h14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
    '</svg></button>'
    '<p class="vis-nascosto" id="nav-label-close">Close menu</p>'
)


def switcher_html(pages: tuple[str, ...]) -> str:
    """Compact language menu: a globe and the current code, opening the five editions."""
    update_href = 'a.href=astEquivalent(lang,location.pathname,location.search,location.hash,pages);'
    watch_hash = ('window.addEventListener("hashchange",function(){' + update_href + '});'
                  if pages != SHARED_PAGES else '')
    links = []
    for code in ('en',) + LOCALES:
        meta = LOCALE_META[code]
        current = ' aria-current="true"' if code == 'en' else ''
        href = home_href(code)
        links.append(
            f'<a href="{href}" hreflang="{meta["html"]}" lang="{meta["html"]}" data-lang="{code}" '
            f'aria-label="{meta["name"]}"{current}>{meta["name"]}</a>'
        )
    details = (
        '<details class="lang" id="lang-details">'
        '<summary class="lang-toggle" aria-label="Choose language">'
        + GLOBE_SVG +
        '<span class="lang-code">EN</span></summary>'
        '<nav class="menu" id="lang-switch" data-i18n-skip aria-label="Language">'
        + ''.join(links) + '</nav></details>'
    )
    script = (
        '<script>' + DETECT_FN +
        'try{var nav=document.getElementById("lang-switch");if(nav){var pages='
        + json.dumps(list(pages)) +
        ';var current=(document.documentElement.lang||"en").toLowerCase();'
        'var codeEl=document.querySelector(".lang-code");if(codeEl)codeEl.textContent=current.toUpperCase();'
        'nav.querySelectorAll("[data-lang]").forEach(function(a){var lang=a.getAttribute("data-lang");'
        + update_href + watch_hash +
        'if(lang===current)a.setAttribute("aria-current","true");else a.removeAttribute("aria-current");'
        'a.addEventListener("click",function(){try{localStorage.setItem("ast-lang",lang);}catch(e){}});});'
        'var langBox=document.getElementById("lang-details");'
        'if(langBox){document.addEventListener("click",function(e){if(langBox.open&&!langBox.contains(e.target))langBox.open=false;});'
        'langBox.addEventListener("keydown",function(e){if(e.key!=="ArrowDown"&&e.key!=="ArrowUp"&&e.key!=="Escape")return;'
        'var items=[].slice.call(nav.querySelectorAll("[data-lang]"));'
        'if(e.key==="Escape"){e.preventDefault();langBox.open=false;var summary=langBox.querySelector("summary");if(summary)summary.focus();return;}'
        'if(!items.length)return;var i=items.indexOf(document.activeElement);'
        'if(i<0){items[0].focus();e.preventDefault();return;}'
        'e.preventDefault();items[(i+(e.key==="ArrowDown"?1:items.length-1))%items.length].focus();});}'
        'var navBtn=document.querySelector(".nav-toggle");var siteNav=document.getElementById("site-nav");'
        'var closeLabel=document.getElementById("nav-label-close");'
        'if(navBtn&&siteNav){var openLabel=navBtn.getAttribute("aria-label");'
        'var setOpen=function(open){navBtn.setAttribute("aria-expanded",open?"true":"false");'
        'siteNav.classList.toggle("is-open",!!open);'
        'if(closeLabel&&openLabel)navBtn.setAttribute("aria-label",open?closeLabel.textContent:openLabel);};'
        'navBtn.addEventListener("click",function(){setOpen(navBtn.getAttribute("aria-expanded")!=="true");});'
        'document.addEventListener("click",function(e){if(navBtn.getAttribute("aria-expanded")==="true"&&!siteNav.contains(e.target)&&!navBtn.contains(e.target))setOpen(false);});'
        'document.addEventListener("keydown",function(e){if(e.key==="Escape"&&navBtn.getAttribute("aria-expanded")==="true"){setOpen(false);navBtn.focus();}});}'
        '}}catch(e){}</script>'
    )
    return details + script


def replace_switcher(text: str, block: str) -> str:
    """Swap either the old code row or the current menu for the canonical switcher."""
    start = text.find('<details class="lang" id="lang-details">')
    if start < 0:
        start = text.find('<nav class="menu" id="lang-switch"')
    if start < 0:
        return text
    marker = 'getElementById("lang-switch")'
    mid = text.find(marker, start)
    if mid < 0:
        return text
    end = text.find('</script>', mid)
    if end < 0:
        return text
    return text[:start] + block + text[end + len('</script>'):]


def refresh_chrome(text: str, switcher: str) -> str:
    """Language menu, section-menu button, clearer security label, and the i18n.css hash."""
    needle = 'try{var saved=null;try{saved=localStorage.getItem("ast-lang");}'
    if 'classList.add("js")' not in text and needle in text:
        text = text.replace(
            needle, 'try{document.documentElement.classList.add("js");}catch(e){}' + needle, 1)
    text = replace_switcher(text, switcher)

    def nav_repl(match: re.Match) -> str:
        nav = match.group(0).replace('>Vuln discoveries</a>', '>Vulnerabilities</a>', 1)
        return nav.replace(
            '<nav class="menu" aria-label="Site sections">',
            '<nav class="menu" id="site-nav" aria-label="Site sections">', 1)

    text = re.sub(
        r'<nav class="menu"(?: id="site-nav")? aria-label="Site sections">.*?</nav>',
        nav_repl, text, count=1, flags=re.S)
    if 'class="nav-toggle"' not in text and '<nav class="menu" id="site-nav"' in text:
        text = text.replace('<nav class="menu" id="site-nav"', NAV_TOGGLE + '<nav class="menu" id="site-nav"', 1)
    css = ROOT / 'assets' / 'i18n.css'
    if css.is_file():
        digest = hashlib.sha256(css.read_bytes()).hexdigest()[:12]
        text = re.sub(
            r'((?:\.\./)?assets/i18n\.css)\?v=[a-f0-9]+',
            lambda m: f'{m.group(1)}?v={digest}', text)
    return text


def detect_html(pages: tuple[str, ...]) -> str:
    # If storage throws, do not auto-redirect: the visitor could not keep an
    # explicit English choice, and the next load would bounce them back.
    return (
        '<script>' + DETECT_FN +
        'try{document.documentElement.classList.add("js");}catch(e){}'
        'try{var saved=null;var storageOk=true;try{saved=localStorage.getItem("ast-lang");}catch(e){storageOk=false;}'
        'if(storageOk){var tz="";try{tz=Intl.DateTimeFormat().resolvedOptions().timeZone||"";}catch(e){}'
        'var dest=astResolveLanguage({ua:navigator.userAgent||"",languages:navigator.languages&&navigator.languages.length?Array.prototype.slice.call(navigator.languages):[navigator.language||""],timezone:tz,path:location.pathname,search:location.search||"",hash:location.hash||"",saved:saved||"",pages:'
        + json.dumps(list(pages)) + '});if(dest)location.replace(dest);}}catch(e){}</script>'
    )


def hreflang_html(page: str) -> str:
    lines = []
    for code in ('en',) + LOCALES:
        lines.append(f'<link rel="alternate" hreflang="{LOCALE_META[code]["html"]}" href="{public_url(page, code)}">')
    lines.append(f'<link rel="alternate" hreflang="x-default" href="{public_url(page, "en")}">')
    for code in ('en',) + LOCALES:
        lines.append(f'<meta property="og:locale:alternate" content="{LOCALE_META[code]["og"]}">')
    # The primary og:locale is separate so a locale page can replace just that value.
    lines.append(f'<meta property="og:locale" content="{LOCALE_META["en"]["og"]}">')
    return '\n'.join(lines)


def dossier_modified_date(text: str) -> str:
    """Read the explicitly maintained dossier update date."""
    updated = re.search(r'<time class="dossier-updated" datetime="(\d{4}-\d{2}-\d{2})">', text)
    return date.fromisoformat(updated[1]).isoformat() if updated else ''


def set_dossier_metadata(text: str, page: str, lang: str) -> str:
    """Keep structured article and breadcrumb metadata aligned with the rendered edition."""
    if not page.endswith('-dossier.html'):
        return text
    h1 = re.search(r'<h1 id="page-title">([^<]+)</h1>', text)
    meta = re.search(r'<meta name="description" content="([^"]+)">', text)
    breadcrumb = re.search(r'<a href="dossiers.html" class="dossier-breadcrumb">([^<]+)</a>', text)
    if not (h1 and meta and breadcrumb):
        return text
    headline = html.unescape(h1[1])
    url = public_url(page, lang)
    publisher = {'@type': 'Organization', 'name': 'AI Science Tracker', 'url': BASE}
    data = {
        '@context': 'https://schema.org',
        '@graph': [
            {'@type': 'Article', 'headline': headline, 'description': html.unescape(meta[1]),
             'inLanguage': lang, 'mainEntityOfPage': {'@type': 'WebPage', '@id': url},
             'author': publisher, 'publisher': publisher},
            {'@type': 'BreadcrumbList', 'itemListElement': [
                {'@type': 'ListItem', 'position': 1, 'item': public_url('dossiers.html', lang),
                 'name': html.unescape(breadcrumb[1])},
                {'@type': 'ListItem', 'position': 2, 'item': url, 'name': headline},
            ]},
        ],
    }
    article = data['@graph'][0]
    updated = dossier_modified_date(text)
    if updated:
        article['dateModified'] = updated
    cover = re.search(r'<img class="dossier-cover" src="(/assets/dossiers/[^"]+)" alt="([^"]+)"', text)
    if cover:
        image_url = BASE + cover[1].lstrip('/')
        article['image'] = image_url
        og_image = f'<meta property="og:image" content="{image_url}">'
        twitter_image = f'<meta name="twitter:image" content="{image_url}">'
        text = re.sub(r'<meta property="og:image" content="[^"]*">', lambda _: og_image, text, count=1)
        if 'name="twitter:image"' in text:
            text = re.sub(r'<meta name="twitter:image" content="[^"]*">', lambda _: twitter_image, text, count=1)
        else:
            text = text.replace(og_image, og_image + '\n' + twitter_image, 1)
        text = re.sub(r'(<meta (?:property="og:image:alt"|name="twitter:image:alt") content=")[^"]*',
                      lambda match: match[1] + cover[2], text)
        text = text.replace('<meta property="og:type" content="website">', '<meta property="og:type" content="article">', 1)
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    metadata = f'<script type="application/ld+json" id="dossier-metadata">{payload}</script>'
    pattern = r'<script type="application/ld\+json" id="dossier-metadata">.*?</script>'
    if re.search(pattern, text):
        return re.sub(pattern, lambda _: metadata, text, count=1)
    return text.replace('</head>', metadata + '\n</head>', 1)


def install_english_chrome(root: Path | None = None) -> None:
    """Add the switcher, first-visit redirect and hreflang links to English pages."""
    root = root or ROOT
    for page in PAGES:
        # The embedded routes only affect a visitor’s current page.
        routes = PAGES if page in NEW_DOSSIER_PAGES else SHARED_PAGES
        switcher = switcher_html(routes)
        path = root / page
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8')
        if 'id="lang-switch"' not in text:
            if '<nav class="menu" aria-label="Site sections">' not in text:
                continue
            text, n = re.subn(
                r'(<nav class="menu" aria-label="Site sections">.*?</nav>)',
                lambda m: m.group(1) + switcher, text, count=1, flags=re.S)
            if n != 1:
                raise RuntimeError(f'{page}: could not insert the language switcher')
        text = refresh_detection(text)
        text = refresh_embedded_detection(text, routes)
        text = refresh_chrome(text, switcher)
        text = rewrite_dirty_homes(text)
        text = clean_home_links(text, '/')
        text = set_switcher_hrefs(text, page)
        text = ensure_twitter(text)
        if 'astResolveLanguage' not in text.split('id="lang-switch"', 1)[0]:
            # Detection lives in <head>, before the switcher copy inside the header.
            marker = '<!-- End Cloudflare Web Analytics -->'
            if marker not in text:
                raise RuntimeError(f'{page}: missing analytics marker for the language script')
            text = text.replace(marker, marker + detect_html(routes), 1)
        if 'assets/i18n.css' not in text and '<link rel="stylesheet" href="styles.css' in text:
            digest = hashlib.sha256((ROOT / 'assets' / 'i18n.css').read_bytes()).hexdigest()[:12]
            link = f'<link rel="stylesheet" href="assets/i18n.css?v={digest}">'
            text = re.sub(
                r'(<link rel="stylesheet" href="styles\.css\?v=[a-f0-9]+">)',
                lambda m: m.group(1) + link, text, count=1)
        block = hreflang_html(page)
        if 'hreflang="x-default"' not in text:
            if '</head>' not in text:
                raise RuntimeError(f'{page}: missing </head>')
            text = text.replace('</head>', block + '\n</head>', 1)
        else:
            text, n = re.subn(
                r'<link rel="alternate" hreflang="en" href="https://aisciencetracker.org/[^"]*">'
                r'(?:\n<link rel="alternate" hreflang="(?!x-default)[^"]+" href="https://aisciencetracker.org/[^"]*">)*'
                r'\n<link rel="alternate" hreflang="x-default" href="https://aisciencetracker.org/[^"]*">'
                r'\n<meta property="og:locale:alternate" content="en_GB">'
                r'\n<meta property="og:locale:alternate" content="it_IT">'
                r'\n<meta property="og:locale:alternate" content="de_DE">'
                r'\n<meta property="og:locale:alternate" content="fr_FR">'
                r'\n<meta property="og:locale:alternate" content="es_ES">'
                r'\n<meta property="og:locale" content="[^"]+">',
                block, text, count=1)
            if n != 1:
                raise RuntimeError(f'{page}: could not refresh hreflang links')
        text = refresh_embedded_detection(text, routes)
        path.write_text(set_dossier_metadata(text, page, 'en'), encoding='utf-8')


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path} must be a JSON object')
    return data


def keep_english() -> set[str]:
    if not KEEP_PATH.exists():
        return set()
    return {line.strip() for line in KEEP_PATH.read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')}


def should_translate(text: str, kept: set[str]) -> bool:
    if text in kept or KEEP_LINE.match(text):
        return False
    if re.fullmatch(r'[a-z]{2}_[A-Z]{2}', text):
        return False
    if re.fullmatch(r'[\w./-]+\.(?:json|csv|md|html|txt|py|yml)', text):
        return False
    if re.fullmatch(r'[a-z][a-z0-9_]*', text) and '_' in text:
        return False
    letters = sum(ch.isalpha() for ch in text)
    if letters < 2 or len(text) <= 2:
        return False
    return True


def templatize(text: str) -> tuple[str, list[str]]:
    nums = NUMBER.findall(text)
    if not nums:
        return text, []
    return NUMBER.sub('{n}', text), nums


def lookup(text: str, table: dict) -> tuple[str, bool]:
    if text in table and isinstance(table[text], str):
        return table[text], True
    template, nums = templatize(text)
    if nums and template in table and isinstance(table[template], str):
        out = table[template]
        for num in nums:
            if '{n}' not in out:
                return text, False
            out = out.replace('{n}', num, 1)
        return out, True
    return text, False


def protect(pattern: str, text: str, vault: list[str]) -> str:
    def stash(match: re.Match) -> str:
        vault.append(match.group(0))
        return f'\x00{len(vault) - 1}\x00'
    return re.sub(pattern, stash, text, flags=re.S)


def restore(text: str, vault: list[str]) -> str:
    return re.sub(r'\x00(\d+)\x00', lambda m: vault[int(m.group(1))], text)


# A leaf is a phrase or sentence whose only nested tags are inline. Link text stays
# inside ⟦ ⟧ so a translation can move it. Locked titles (share pages, organization
# names) use ⟦*⟧ and keep their original element.
_STRUCT = r'p|li|h[1-4]|div|ul|ol|section|table|thead|tbody|tr|details|nav|form|figure|header|footer|main|article|script|style|blockquote|dl'
_LEAF = re.compile(
    rf'<(p|li|h[1-4]|figcaption|summary|button|label|dt|dd|caption|option|th|td|a|title|desc|text)\b([^>]*)>'
    rf'((?:[^<]|<(?!/?(?:{_STRUCT})\b))*?)</\1>',
    re.S)
_INLINE = re.compile(r'<((?:a|b|strong|em|i|span|code|time|small|abbr))\b([^>]*)>(.*?)</\1>', re.S)
_ATTR = re.compile(r'(\s)(placeholder|aria-label|title|alt|content)(=)(["\'])(.*?)\4', re.S)


def _marker_key(inner: str):
    slots = []

    def repl(match: re.Match) -> str:
        tag, attrs, body = match.group(1), match.group(2), match.group(3)
        href = re.search(r'\bhref="([^"]*)"', attrs)
        target = href.group(1) if href else ''
        locked = tag == 'a' and (target.startswith(('share/', '../share/', 'profile.html?org=')))
        if locked:
            slots.append(match.group(0))
            return '⟦*⟧'
        text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', body))).strip()
        slots.append((tag, attrs, text))
        return f'⟦{text}⟧'

    masked = _INLINE.sub(repl, inner)
    if re.search(r'<[a-zA-Z!/]', masked):
        return None, None
    return re.sub(r'\s+', ' ', html.unescape(masked)).strip(), slots


def _rebuild(translated: str, slots: list) -> str | None:
    parts = re.split(r'⟦(.*?)⟧', translated)
    if len(parts) != len(slots) * 2 + 1:
        return None
    out = []
    for index, slot in enumerate(slots):
        out.append(html.escape(parts[index * 2], quote=False))
        if isinstance(slot, str):
            out.append(slot)
        else:
            tag, attrs, _old = slot
            out.append(f'<{tag}{attrs}>{html.escape(parts[index * 2 + 1], quote=False)}</{tag}>')
    out.append(html.escape(parts[-1], quote=False))
    return ''.join(out)


def translate_leaves(text: str, table: dict, kept: set[str], missing: list[str]) -> str:
    def repl(match: re.Match) -> str:
        tag, attrs, inner = match.group(1), match.group(2), match.group(3)
        key, slots = _marker_key(inner)
        if not key:
            return match.group(0)
        translated, found = lookup(key, table)
        if not found:
            if should_translate(key, kept):
                missing.append(key)
            return match.group(0)
        if not slots:
            return f'<{tag}{attrs}>{html.escape(translated, quote=False)}</{tag}>'
        rebuilt = _rebuild(translated, slots)
        if rebuilt is None:
            missing.append(key)
            return match.group(0)
        return f'<{tag}{attrs}>{rebuilt}</{tag}>'

    return _LEAF.sub(repl, text)


# Opt-in: a plain-text <span data-i18n> is translated wherever it sits, even inside a locked
# share link or nested inline markup that the leaf pass skips. Editorial text only, never source titles.
_MARKED = re.compile(r'(<span\b[^>]*\bdata-i18n\b[^>]*>)([^<]*)(</span>)')


def translate_marked(text: str, table: dict, kept: set[str], missing: list[str]) -> str:
    def repl(match: re.Match) -> str:
        key = html.unescape(match.group(2)).strip()
        translated, found = lookup(key, table)
        if not found:
            if should_translate(key, kept):
                missing.append(key)
            return match.group(0)
        return f'{match.group(1)}{html.escape(translated, quote=False)}{match.group(3)}'

    return _MARKED.sub(repl, text)


def translate_attributes(text: str, table: dict, kept: set[str], missing: list[str]) -> str:
    def repl(match: re.Match) -> str:
        space, name, eq, quote, raw = match.group(1), match.group(2), match.group(3), match.group(4), match.group(5)
        decoded = html.unescape(raw).strip()
        if name == 'content' and (
            'self' in decoded or decoded.startswith(('#', 'default-src')) or 'noindex' in decoded
            or 'device-width' in decoded or re.fullmatch(r'[a-z]{2}_[A-Z]{2}', decoded)
            or decoded in {'website', 'summary_large_image', 'article'}
        ):
            return match.group(0)
        translated, found = lookup(decoded, table)
        if not found:
            if should_translate(decoded, kept):
                missing.append(decoded)
            return match.group(0)
        return f'{space}{name}{eq}{quote}{html.escape(translated, quote=True)}{quote}'

    return _ATTR.sub(repl, text)


def translate_document(page_html: str, table: dict, kept: set[str]) -> tuple[str, list[str]]:
    vault: list[str] = []
    missing: list[str] = []
    protected = protect(r'<script\b[^>]*>.*?</script>', page_html, vault)
    protected = protect(r'<style\b[^>]*>.*?</style>', protected, vault)
    protected = protect(
        r'<(nav|ol|ul|div)\b[^>]*\bdata-i18n-skip\b[^>]*>.*?</\1>', protected, vault)
    protected = translate_leaves(protected, table, kept, missing)
    protected = translate_marked(protected, table, kept, missing)
    protected = translate_attributes(protected, table, kept, missing)
    return restore(protected, vault), missing


def split_url(value: str) -> tuple[str, str]:
    for mark in ('#', '?'):
        if mark in value:
            path, rest = value.split(mark, 1)
            return path, mark + rest
    return value, ''


def rewrite_url(value: str, lang: str, page: str) -> str:
    if re.match(r'^(?:https?:|data:|mailto:|#|/)', value):
        return value
    path, suffix = split_url(value)
    if page == '404.html':
        # 404.html uses a site-root <base>, so assets stay relative and translated pages gain a prefix.
        if path in PAGES:
            return f'{lang}/{path}{suffix}'
        return value
    if path in PAGES:
        return value
    if path in ASSET_FILES or any(path.startswith(prefix) for prefix in ASSET_PREFIXES):
        return f'../{path}{suffix}'
    return value


def rewrite_attrs(page_html: str, lang: str, page: str) -> str:
    def repl(match: re.Match) -> str:
        return f'{match.group(1)}={match.group(2)}{rewrite_url(match.group(3), lang, page)}{match.group(2)}'
    return re.sub(r'(href|src)=(["\'])([^"\']+)\2', repl, page_html)


def rewrite_script_paths(page_html: str) -> str:
    def repl_script(match: re.Match) -> str:
        body = match.group(2)
        for folder in ('share/', 'profiles/', 'data/', 'api/', 'og/'):
            body = body.replace(f'"{folder}', f'"../{folder}')
            body = body.replace(f"'{folder}", f"'../{folder}")
            body = body.replace(f'`{folder}', f'`../{folder}')
        return match.group(1) + body + '</script>'
    return re.sub(r'(<script\b(?![^>]*\bsrc=)[^>]*>)(.*?)(</script>)', lambda m: repl_script(m), page_html, flags=re.S)


def retarget_switcher(page_html: str, lang: str, page: str) -> str:
    """Language links are root URLs (/ and /it/), so they do not become /index.html."""
    del lang
    return set_switcher_hrefs(page_html, page)


def mark_lang_code(page_html: str, lang: str) -> str:
    """Show this edition's code before JavaScript runs."""
    label = LOCALE_META[lang]['label']
    return page_html.replace('<span class="lang-code">EN</span>', f'<span class="lang-code">{label}</span>', 1)


def mark_switcher(page_html: str, lang: str) -> str:
    def repl(match: re.Match) -> str:
        block = match.group(0).replace(' aria-current="true"', '')
        return block.replace(f'data-lang="{lang}"', f'data-lang="{lang}" aria-current="true"', 1)
    return re.sub(r'<nav class="menu" id="lang-switch".*?</nav>', repl, page_html, count=1, flags=re.S)


RUNTIME_FILE = 'runtime.js'


def runtime_script(lang: str, messages: dict, discoveries: dict) -> str:
    root = '' if lang == 'en' else '../'
    payload = {
        'AST_MESSAGES': messages,
        'AST_DISCOVERIES': discoveries,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    intl = LOCALE_META[lang]['intl']
    return (
        'Object.assign(globalThis,' + raw + ');'
        f'globalThis.AST_SITE_ROOT={json.dumps(root)};'
        f'globalThis.AST_INTL_LOCALE={json.dumps(intl)};'
        'if(globalThis.CatalogUI){CatalogUI.messages=AST_MESSAGES;CatalogUI.dateLocale=AST_INTL_LOCALE;}\n'
    )


def runtime_tag(lang: str, page: str, body: str) -> str:
    """One cacheable bundle per language instead of ~2.4 MB inlined into every page."""
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()[:12]
    # 404.html resolves against a site-root <base>.
    src = f'{lang}/{RUNTIME_FILE}' if page == '404.html' else RUNTIME_FILE
    return f'<script src="{src}?v={digest}"></script>'


def refresh_embedded_detection(text: str, pages: tuple[str, ...]) -> str:
    """Replace an already-inserted copy of the detector with the current one."""
    if 'astResolveLanguage' not in text:
        return text
    fresh = DETECT_FN.strip()
    text, n = re.subn(
        r'(?:globalThis\.astCleanPath = function \(path\) \{.*?\n\};\n)?'
        r'globalThis\.astResolveLanguage = function \(input\) \{.*?globalThis\.astEquivalent = function \(lang, path, search, hash, pages\) \{.*?\n\};',
        fresh, text, flags=re.S)
    if n < 1:
        raise RuntimeError('could not refresh the language detector')
    caller = (
        'try{document.documentElement.classList.add("js");}catch(e){}'
        'try{var saved=null;var storageOk=true;try{saved=localStorage.getItem("ast-lang");}catch(e){storageOk=false;}'
        'if(storageOk){var tz="";try{tz=Intl.DateTimeFormat().resolvedOptions().timeZone||"";}catch(e){}'
        'var dest=astResolveLanguage({ua:navigator.userAgent||"",languages:navigator.languages&&navigator.languages.length?Array.prototype.slice.call(navigator.languages):[navigator.language||""],timezone:tz,path:location.pathname,search:location.search||"",hash:location.hash||"",saved:saved||"",pages:'
        + json.dumps(list(pages)) + '});if(dest)location.replace(dest);}}catch(e){}'
    )
    text, n = re.subn(
        r'try\{var saved=null;try\{saved=localStorage\.getItem\("ast-lang"\);\}catch\(e\)\{\}var tz="";try\{tz=Intl\.DateTimeFormat\(\)\.resolvedOptions\(\)\.timeZone\|\|"";\}catch\(e\)\{\}var dest=astResolveLanguage\(\{.*?\}\);if\(dest\)location\.replace\(dest\);\}catch\(e\)\{\}',
        caller, text, count=1, flags=re.S)
    if 'location.replace(dest)' in text and 'storageOk' not in text:
        raise RuntimeError('could not refresh the language redirect')
    return text


def retarget_head(page_html: str, page: str, lang: str) -> str:
    meta = LOCALE_META[lang]
    page_html = re.sub(r'<html lang="en"', f'<html lang="{meta["html"]}"', page_html, count=1)
    if page != '404.html':
        english = public_url(page, 'en')
        local = public_url(page, lang)
        page_html = page_html.replace(f'<link rel="canonical" href="{english}">', f'<link rel="canonical" href="{local}">')
        page_html = page_html.replace(f'<meta property="og:url" content="{english}">', f'<meta property="og:url" content="{local}">')
        page_html = page_html.replace('"inLanguage":"en"', f'"inLanguage":"{meta["html"]}"')
        page_html = page_html.replace(
            f'<meta property="og:locale" content="{LOCALE_META["en"]["og"]}">',
            f'<meta property="og:locale" content="{meta["og"]}">')
    return page_html


def js_message_keys(root: Path | None = None) -> set[str]:
    root = root or ROOT
    keys = set()
    files = list((root / 'assets').glob('*.js')) + [root / name for name in PAGES if (root / name).exists()]
    files.append(root / 'scripts' / 'i18n_site.py')
    for path in files:
        if not path.exists():
            continue
        for match in TR_CALL.finditer(path.read_text(encoding='utf-8', errors='ignore')):
            keys.add(match.group(2).encode('utf-8').decode('unicode_escape') if '\\' in match.group(2) else match.group(2))
    return keys


def required_keys(root: Path | None = None) -> tuple[set[str], list[str]]:
    """English strings the catalogs must cover, plus prose that is still untranslated."""
    root = root or ROOT
    kept = keep_english()
    needed = set(js_message_keys(root))
    dossier_keys = load_json(DOSSIER_MESSAGES)
    missing_preview = []
    empty = {}
    for page in PAGES:
        path = root / page
        if not path.exists():
            continue
        _translated, missing = translate_document(path.read_text(encoding='utf-8'), empty, kept)
        for item in missing:
            template, nums = templatize(item)
            key = template if nums and item not in dossier_keys else item
            needed.add(key)
            missing_preview.append(f'{page}: {key}')
    return needed, missing_preview


def sync_english_catalog(root: Path | None = None) -> int:
    root = root or ROOT
    needed, _ = required_keys(root)
    needed -= set(load_json(DOSSIER_MESSAGES))
    path = MESSAGES / 'en.json'
    current = load_json(path)
    for key in sorted(needed):
        current.setdefault(key, key)
    # Drop keys that the pages no longer use, so a stale translation cannot hide a gap.
    current = {key: current[key] for key in sorted(needed)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return len(current)


def catalog_errors(root: Path | None = None) -> list[str]:
    root = root or ROOT
    english = load_json(MESSAGES / 'en.json')
    errors = []
    needed, _ = required_keys(root)
    dossier_messages = load_json(DOSSIER_MESSAGES)
    for key in sorted(needed - set(english) - set(dossier_messages)):
        errors.append(f'en.json is missing {key!r}')
    for lang in LOCALES:
        for key, translations in dossier_messages.items():
            if not translations.get(lang):
                errors.append(f'dossiers.json is missing {lang} for {key!r}')
        table = load_json(MESSAGES / f'{lang}.json')
        for key in sorted(set(english) - set(table)):
            errors.append(f'{lang}.json is missing {key!r}')
        for key, value in table.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f'{lang}.json has an empty value for {key!r}')
        discoveries = load_json(DISCOVERIES / f'{lang}.json')
        for entry_id, row in discoveries.items():
            if not isinstance(row, dict) or not isinstance(row.get('summary', ''), str):
                errors.append(f'{lang} discovery {entry_id} needs a summary string')
    return errors


def write_locale_pages(root: Path | None = None, strict: bool = True) -> None:
    root = root or ROOT
    kept = keep_english()
    english = load_json(MESSAGES / 'en.json')
    problems = []
    dossier_messages = load_json(DOSSIER_MESSAGES)
    for lang in LOCALES:
        table = load_json(MESSAGES / f'{lang}.json')
        discoveries = load_json(DISCOVERIES / f'{lang}.json')
        # English catalog values are the source strings; a locale file may omit nothing checked above.
        merged = dict(table)
        # Editorial strings stay out of the runtime bundle shared by other pages.
        dossier_table = merged | {key: values[lang] for key, values in dossier_messages.items()}
        out_dir = root / lang
        out_dir.mkdir(parents=True, exist_ok=True)
        runtime_body = runtime_script(lang, merged, discoveries)
        (out_dir / RUNTIME_FILE).write_text(runtime_body, encoding='utf-8')
        for page in PAGES:
            source = root / page
            if not source.exists():
                continue
            text = source.read_text(encoding='utf-8')
            if 'id="lang-switch"' not in text:
                continue
            has_dossier_copy = 'dossier' in page or page in ('guide.html', 'models.html', 'security.html')
            text, missing = translate_document(text, dossier_table if has_dossier_copy else merged, kept)
            if missing:
                problems.extend(f'{lang}/{page}: {item}' for item in missing[:8])
                if len(missing) > 8:
                    problems.append(f'{lang}/{page}: {len(missing) - 8} more untranslated strings')
            text = retarget_head(text, page, lang)
            text = mark_switcher(text, lang)
            text = mark_lang_code(text, lang)
            if page != '404.html':
                text = retarget_switcher(text, lang, page)
            if page != '404.html':
                text = rewrite_script_paths(text)
            text = set_dossier_metadata(text, page, lang)
            text = rewrite_attrs(text, lang, page)
            text = clean_home_links(text, home_href(lang))
            text = retarget_iamops(text, lang)
            if 'dossier' not in page:
                injection = runtime_tag(lang, page, runtime_body)
                text = text.replace('</head>', injection + '\n</head>', 1)
            (out_dir / page).write_text(text, encoding='utf-8')
    if problems and strict:
        preview = '\n'.join(problems[:40])
        raise SystemExit(f'Untranslated prose ({len(problems)}):\n{preview}')
    # Silence unused in case a locale inherits English explicitly.
    del english


def sitemap_entries() -> str:
    """Extra <url> rows for language editions, with hreflang alternates on every static page."""
    rows = []
    for page in SITEMAP_PAGES:
        links = [f'<xhtml:link rel="alternate" hreflang="en" href="{html.escape(public_url(page, "en"), quote=True)}"/>']
        for code in LOCALES:
            links.append(f'<xhtml:link rel="alternate" hreflang="{code}" href="{html.escape(public_url(page, code), quote=True)}"/>')
        links.append(f'<xhtml:link rel="alternate" hreflang="x-default" href="{html.escape(public_url(page, "en"), quote=True)}"/>')
        block = ''.join(links)
        rows.append(f'<url><loc>{html.escape(public_url(page, "en"), quote=True)}</loc>{block}</url>\n')
        for code in LOCALES:
            rows.append(f'<url><loc>{html.escape(public_url(page, code), quote=True)}</loc>{block}</url>\n')
    return ''.join(rows)


def main() -> None:
    if '--sync-en' in sys.argv:
        count = sync_english_catalog()
        print(f'{count} English message keys')
        return
    errors = catalog_errors() if '--check' in sys.argv or '--sync-en' not in sys.argv else []
    if '--check' in sys.argv:
        if errors:
            raise SystemExit('\n'.join(errors[:50]))
        print('language catalogs cover every English key')
        return
    if errors and '--sync-en' not in sys.argv:
        raise SystemExit('\n'.join(errors[:50]))
    install_english_chrome()
    write_locale_pages()
    print(f'wrote {", ".join(LOCALES)} editions of {len(PAGES)} pages')


if __name__ == '__main__':
    main()
