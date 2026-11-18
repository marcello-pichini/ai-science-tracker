"""First-party research blog adapters. Listings yield candidates, never admissions."""
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from . import fetch

SOURCES = {
    'microsoft-research': {'kind': 'feed', 'url': 'https://www.microsoft.com/en-us/research/feed/',
                           'paths': ('/en-us/research/blog/',)},
    'meta-ai': {'kind': 'html', 'url': 'https://ai.meta.com/blog/', 'paths': ('/blog/',)},
    'mit-ai': {'kind': 'feed', 'url': 'https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml',
               'paths': ('/',)},
    'eth-news': {'kind': 'feed', 'url': 'https://www.ethz.ch/en/news-und-veranstaltungen/eth-news/news/_jcr_content.feed.html',
                 'paths': ('/en/news-and-events/eth-news/news/', '/en/news-und-veranstaltungen/eth-news/news/')},
    'stanford-hai': {'kind': 'html', 'url': 'https://hai.stanford.edu/news', 'paths': ('/news/',)},
    'berkeley-bair': {'kind': 'html', 'url': 'https://bair.berkeley.edu/blog/archive/', 'paths': ('/blog/',)},
    'epfl-ai': {'kind': 'html', 'url': 'https://ai.epfl.ch/news/', 'paths': ('/news/',),
                'article_hosts': ('actu.epfl.ch',)},
}


def normalize_date(value):
    """Keep only parseable dates; missing listing dates stay explicitly unknown."""
    value = (value or '').strip()
    if not value:
        return ''
    if re.match(r'^\d{4}-\d{2}-\d{2}(?:$|T| )', value):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return ''
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        pass
    for pattern in ('%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %B, %Y', '%d %b %Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    return ''


def feed_items(xml_text):
    root = ET.fromstring(xml_text)
    if root.tag.rsplit('}', 1)[-1] not in ('rss', 'RDF', 'feed'):
        raise ValueError('Expected RSS, RDF or Atom; received another document')
    for item in root.iter():
        kind = item.tag.rsplit('}', 1)[-1]
        if kind not in ('item', 'entry'):
            continue
        fields = {}
        link = ''
        for child in item:
            name = child.tag.rsplit('}', 1)[-1]
            fields.setdefault(name, ''.join(child.itertext()).strip())
            if name == 'link' and (kind == 'item' or child.get('rel', 'alternate') == 'alternate'):
                link = child.get('href') or (child.text or '').strip()
        raw_date = fields.get('pubDate') or fields.get('published') or fields.get('date') or fields.get('updated')
        yield (fields.get('title', ''), link, normalize_date(raw_date),
               fields.get('description') or fields.get('summary') or fields.get('content') or '')


class Listing(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.next_links = [], []
        self.anchor = None
        self.cards = []
        self.time_depth = 0
        self.time_text = []
        self.dynamic_pagination = False
        self.hidden = 0
        self.heading_text = None
        self.last_heading = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('h2', 'h3', 'h4'):
            self.heading_text = []
        if tag == 'article':
            self.cards.append({'date': ''})
        if tag == 'time':
            self.time_depth += 1
            self.time_text = []
            if self.cards:
                self.cards[-1]['date'] = normalize_date(attrs.get('datetime'))
        if tag == 'a':
            self.anchor = {'url': attrs.get('href', ''), 'text': [], 'label': attrs.get('aria-label', ''),
                           'rel': attrs.get('rel', ''), 'title': attrs.get('title', ''),
                           'card': self.cards[-1] if self.cards else {}}
        elif tag == 'img' and self.anchor is not None and attrs.get('alt'):
            self.anchor['text'].append(attrs['alt'])

    def handle_data(self, text):
        if self.hidden:
            return
        if self.anchor is not None:
            self.anchor['text'].append(text)
        if self.heading_text is not None:
            self.heading_text.append(text)
        if self.time_depth:
            self.time_text.append(text)
        if re.search(r'\bload more\b|\bshow more\b|\bsee all news\b', text, re.I):
            self.dynamic_pagination = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('h2', 'h3', 'h4') and self.heading_text is not None:
            self.last_heading = ' '.join(' '.join(self.heading_text).split())
            self.heading_text = None
        if tag == 'time':
            if self.cards and not self.cards[-1]['date']:
                self.cards[-1]['date'] = normalize_date(' '.join(self.time_text))
            self.time_depth = max(0, self.time_depth - 1)
        if tag == 'article' and self.cards:
            self.cards.pop()
        if tag == 'a' and self.anchor is not None:
            anchor = self.anchor
            anchor['title'] = ' '.join(' '.join(anchor['text']).split()) or anchor['title'] or anchor['label']
            if re.fullmatch(r'(?:read|learn) more[. …]*|\(?more[.…]*\)?', anchor['title'], re.I) and self.last_heading:
                anchor['title'] = self.last_heading
            label = anchor['title'] + ' ' + anchor['label']
            if 'next' in anchor['rel'].split() or re.search(r'\bnext(?: page)?\b', label, re.I):
                self.next_links.append(anchor['url'])
            self.links.append(anchor)
            self.anchor = None


def canonical_article(source, base, href):
    absolute = urljoin(base, href)
    parsed = urlsplit(absolute)
    origin = urlsplit(source['url'])
    hosts = {origin.hostname, *(source.get('article_hosts', ()))}
    if origin.hostname in ('www.ethz.ch', 'ethz.ch'):
        hosts.update(('www.ethz.ch', 'ethz.ch'))
    if parsed.scheme not in ('https', 'http') or parsed.hostname not in hosts:
        return None
    if parsed.hostname != origin.hostname and parsed.hostname in source.get('article_hosts', ()):
        allowed = parsed.path.startswith('/news/')
    else:
        allowed = any(parsed.path.startswith(p) and parsed.path.rstrip('/') != p.rstrip('/')
                      for p in source['paths'])
    if not allowed or parsed.path.rstrip('/') in ('/blog/archive', '/blog/tag', '/blog/category'):
        return None
    if re.search(r'/(?:tag|tags|category|categories|page)/', parsed.path):
        return None
    return urlunsplit(('https', parsed.netloc, parsed.path, '', ''))


def source_items(name, fetcher=None, report=None):
    """Follow declared next links without a page cap; report dynamic/inaccessible coverage."""
    fetcher = fetcher or fetch.get_text
    report = report if report is not None else {}
    source = SOURCES[name]
    current = source['url']
    visited, found = set(), {}
    report.update(source=name, url=current, kind=source['kind'], status='running', pages=0, items=0)
    try:
        while current and current not in visited:
            visited.add(current)
            body = fetcher(current, max_bytes=20 * 1024 ** 2)
            report['pages'] += 1
            if source['kind'] == 'feed':
                items = list(feed_items(body))
                current = None
                report['coverage'] = 'available feed entries; not a complete historical archive'
            else:
                page = Listing()
                page.feed(body)
                items = [(a['title'], a['url'], a['card'].get('date', ''), '') for a in page.links]
                next_page = next((urljoin(current, href) for href in page.next_links
                                  if urlsplit(urljoin(current, href)).netloc == urlsplit(source['url']).netloc
                                  and (urlsplit(urljoin(current, href)).path.rstrip('/') == urlsplit(source['url']).path.rstrip('/')
                                       or any(re.fullmatch(re.escape(p.rstrip('/')) + r'/page/\d+/?', urlsplit(urljoin(current, href)).path)
                                              for p in source['paths']))), None)
                if page.next_links and not next_page:
                    report['coverage'] = 'partial: next-page link is outside the verified listing routes'
                if page.dynamic_pagination and not next_page:
                    report['coverage'] = 'partial: dynamic load-more requires a separately verified endpoint'
                current, base = next_page, current
            if source['kind'] == 'feed':
                base = source['url']
            for title, href, date_value, summary in items:
                url = canonical_article(source, base, href)
                if not url or not title or title.lower().strip() in ('read more', 'learn more', 'more'):
                    continue
                published = normalize_date(date_value)
                previous = found.get(url)
                if previous:
                    if published and previous[2] and published != previous[2]:
                        conflict = {'url': url, 'dates': sorted({published, previous[2]})}
                        if conflict not in report.setdefault('date_conflicts', []):
                            report['date_conflicts'].append(conflict)
                    title = max((previous[0], title), key=len)
                    published = previous[2] or published
                    summary = previous[3] or summary
                found[url] = (title, url, published, summary)
        if current in visited:
            report['coverage'] = 'partial: pagination cycle detected'
        if not found:
            report.update(status='partial', error='No article entries parsed; do not treat this as no news')
        elif str(report.get('coverage', '')).startswith('partial:'):
            report['status'] = 'partial'
        else:
            report['status'] = 'ok'
        report['items'] = len(found)
        report['unknown_dates'] = sum(not row[2] for row in found.values())
        yield from found.values()
    except Exception as exc:
        report.update(status='partial' if found else 'error', error=f'{type(exc).__name__}: {exc}', items=len(found))
        yield from found.values()
