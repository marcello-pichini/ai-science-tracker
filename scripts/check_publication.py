"""Read-only checks of the deployed site, Hugging Face files and Zenodo version."""
import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PAGES = ('index.html', 'models.html', 'model-progress.html', 'security.html',
         'dataset.html', 'methodology.html', 'profiles/index.html')
DATA = ('discoveries.json', 'vulnerabilities.json', 'models.json',
        'model-progress.json', 'swe-bench.json')
HF_FILES = ('discoveries.json', 'discoveries.csv', 'vulnerabilities.json', 'vulnerabilities.csv')
MAX_BYTES = 64 * 1024 * 1024


def fetch(url, attempts=3, inspect=False):
    for attempt in range(attempts):
        try:
            request = Request(url, headers={'User-Agent': 'AI-Science-Tracker-Monitor/1.0',
                                            'Cache-Control': 'no-cache'})
            with urlopen(request, timeout=20) as response:
                body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError('Response exceeds the monitor size limit')
                if inspect:
                    return body, response.status, response.geturl(), response.headers.get_all('X-Robots-Tag', [])
                return body
        except (OSError, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = self.heading = False
        self.assets = set()
        self.text = []
        self.hidden = 0
        self.canonical = []
        self.robots = []
        self.identity = {'title': [], 'h1': []}
        self.identity_tag = None
        self.snapshot = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.title |= tag == 'title'
        self.heading |= tag == 'h1'
        if tag in self.identity:
            self.identity_tag = tag
        if tag == 'html':
            self.snapshot = attrs.get('data-page-snapshot')
        if tag == 'link' and 'canonical' in attrs.get('rel', '').casefold().split():
            self.canonical.append(attrs.get('href'))
        if tag == 'meta' and attrs.get('name', '').casefold() in ('robots', 'googlebot'):
            self.robots.append(attrs.get('content', ''))
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'script' and attrs.get('src'):
            self.assets.add(attrs['src'])
        if tag == 'link' and 'stylesheet' in attrs.get('rel', '').split() and attrs.get('href'):
            self.assets.add(attrs['href'])

    def handle_endtag(self, tag):
        if tag == self.identity_tag:
            self.identity_tag = None
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if self.identity_tag:
            self.identity[self.identity_tag].append(data)
        if not self.hidden:
            self.text.append(data)

    def signature(self):
        return tuple(' '.join(''.join(self.identity[tag]).split()) for tag in ('title', 'h1'))


def check_page(expected, actual, url, final_url, status, headers):
    if status != 200 or final_url != url:
        return 'fail', f'Expected HTTP 200 at {url}, received {status} at {final_url}'
    if not all(actual.signature()) or actual.signature() != expected.signature():
        return 'fail', 'Published title or main heading differs from the deployed Git snapshot'
    if len(expected.canonical) != 1 or actual.canonical != expected.canonical:
        return 'fail', 'Published canonical is missing, ambiguous or differs from the deployed Git snapshot'
    if actual.snapshot != expected.snapshot:
        return 'fail', 'Published HTML snapshot stamp differs from the deployed Git snapshot'
    directives = ' '.join([*actual.robots, *headers]).casefold()
    if re.search(r'\b(?:noindex|none)\b', directives):
        return 'fail', 'Published indexable page carries a noindex directive'
    return 'pass', 'HTTP response and indexable page identity match the deployed Git snapshot'


def same_data(expected, actual, filename):
    if filename.endswith('.json'):
        return json.loads(expected) == json.loads(actual)
    return expected == actual


def check_zenodo(body, release, now=None):
    page = Page()
    page.feed(body.decode('utf-8'))
    match = re.search(r'\bVersion\s+(v[\w.\-]+)', ' '.join(page.text))
    actual = match.group(1) if match else None
    if actual == release['tagName']:
        return 'pass', f"Latest archived version is {actual}"
    published = dt.datetime.fromisoformat(release['publishedAt'].replace('Z', '+00:00'))
    age = (now or dt.datetime.now(dt.timezone.utc)) - published
    status = 'pending' if age < dt.timedelta(hours=2) else 'fail'
    return status, f"Expected {release['tagName']}; Zenodo currently reports {actual or 'no version'}"


def check(root, site, hf, release=None, fetcher=fetch):
    results, assets = [], set()

    def record(name, action):
        try:
            status, detail = action()
        except Exception as exc:
            status, detail = 'fail', f'{type(exc).__name__}: {exc}'
        results.append({'check': name, 'status': status, 'detail': detail})

    def compare(path, url):
        expected = path.read_bytes()
        separator = '&' if '?' in url else '?'
        url += separator + 'monitor=' + hashlib.sha256(expected).hexdigest()[:16]
        if not same_data(expected, fetcher(url), path.name):
            return 'fail', 'Published contents differ from the deployed Git snapshot'
        return 'pass', 'Published contents match the deployed Git snapshot'

    paths = list(PAGES)
    discoveries = json.loads((root / 'data/discoveries.json').read_text())
    if discoveries:
        paths.append(f"share/{discoveries[-1]['id']}.html")
    security_index = root / 'profiles/security-index.html'
    if security_index.is_file():
        paths.append('profiles/security-index.html')
        cases = json.loads((root / 'data/vulnerabilities.json').read_text())
        if cases:
            latest = max(cases, key=lambda row: (row['disclosure_date'], row['id']))
            paths.append(f"profiles/security-{latest['id']}.html")
    for filename in ('robots.txt', 'sitemap.xml'):
        if (root / filename).is_file():
            record('site/' + filename, lambda name=filename: compare(root / name, urljoin(site, name)))
    for path in paths:
        def page_check(path=path):
            url = urljoin(site, path)
            expected, page = Page(), Page()
            expected.feed((root / path).read_text(encoding='utf-8'))
            if fetcher is fetch:
                body, status, final_url, headers = fetch(url, inspect=True)
            else:
                body, status, final_url, headers = fetcher(url), 200, url, []
            page.feed(body.decode('utf-8'))
            result = check_page(expected, page, url, final_url, status, headers)
            if result[0] != 'pass':
                return result
            for asset in page.assets:
                absolute = urljoin(url, asset)
                if urlsplit(absolute).netloc == urlsplit(site).netloc:
                    assets.add(absolute)
            return result
        record('site/' + path, page_check)
    for url in sorted(assets):
        relative = urlsplit(url).path.lstrip('/')
        if '..' in Path(relative).parts:
            record('asset/' + relative, lambda: ('fail', 'Unsafe asset path'))
        else:
            record('asset/' + relative, lambda url=url, relative=relative:
                   compare(root / relative, url))
    for name in DATA:
        local = root / 'data' / name
        if local.exists():
            record('site/data/' + name, lambda local=local, name=name:
                   compare(local, urljoin(site, 'data/' + name)))
    record('site/api/v1/index.json', lambda:
           compare(root / 'api/v1/index.json', urljoin(site, 'api/v1/index.json')))
    for name in HF_FILES:
        record('hugging-face/' + name, lambda name=name:
               compare(root / 'data' / name, hf.rstrip('/') + '/' + name))
    if release:
        def zenodo_check():
            try:
                return check_zenodo(fetcher('https://doi.org/10.5281/zenodo.24217686'), release)
            except Exception:
                published = dt.datetime.fromisoformat(release['publishedAt'].replace('Z', '+00:00'))
                if dt.datetime.now(dt.timezone.utc) - published < dt.timedelta(hours=2):
                    return 'pending', 'Zenodo has not become reachable within the archive grace period'
                raise
        record('zenodo/latest-version', zenodo_check)
    else:
        record('zenodo/latest-version', lambda: ('fail', 'Latest GitHub release metadata is missing'))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--site', default='https://aisciencetracker.org/')
    parser.add_argument('--hf', default='https://huggingface.co/datasets/marcello-pichini/ai-science-tracker/resolve/main')
    parser.add_argument('--release-metadata', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        release = json.loads(args.release_metadata.read_text()) if args.release_metadata else None
        results = check(args.root, args.site.rstrip('/') + '/', args.hf, release)
    except Exception as exc:
        results = [{'check': 'setup', 'status': 'fail', 'detail': f'{type(exc).__name__}: {exc}'}]
    report = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'results': results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    for result in results:
        print(f"{result['status'].upper()}: {result['check']} — {result['detail']}")
    return int(any(r['status'] == 'fail' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
