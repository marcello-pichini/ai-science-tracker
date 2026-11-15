"""Report catalog links that no longer exist (HTTP 404 or 410).

Run now and then: python3 scripts/check_links.py
Not part of the tests: many publishers answer 403 to scripts while working in a browser.
"""
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {'discoveries': ('source_url', 'paper_url'),
          'vulnerabilities': ('source_url', 'ai_source_url', 'advisory_url')}


def status(url):
    return subprocess.run(['curl', '-sL', '-m', '30', '-o', '/dev/null', '-w', '%{http_code}',
                           '-A', 'Mozilla/5.0', url], capture_output=True, text=True).stdout


def main():
    uses = {}
    for name, fields in FIELDS.items():
        for record in json.loads((ROOT / 'data' / f'{name}.json').read_text()):
            for field in fields:
                if record.get(field):
                    uses.setdefault(record[field], []).append(f"{name}:{record['id']}:{field}")
    with ThreadPoolExecutor(12) as pool:
        codes = dict(zip(uses, pool.map(status, uses)))
    gone = {u: c for u, c in codes.items() if c in ('404', '410')}
    for url, code in sorted(gone.items()):
        print(code, url, *uses[url], sep='\n  ')
    print(f'{len(gone)} gone of {len(codes)} links')
    return 1 if gone else 0


if __name__ == '__main__':
    sys.exit(main())
