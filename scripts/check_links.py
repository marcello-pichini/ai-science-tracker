"""Report catalog links that no longer exist (HTTP 404 or 410).

Run now and then: python3 scripts/check_links.py
Not part of the tests: many publishers answer 403 to scripts while working in a browser.
"""
import argparse
import datetime
import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
FIELDS = {'discoveries': ('source_url', 'paper_url')}


def status(url, timeout=10):
    if urlsplit(url).scheme not in ('http', 'https'):
        return 'invalid'
    return subprocess.run(['curl', '-sL', '--max-redirs', '5', '--proto', '=http,https',
                           '--proto-redir', '=http,https', '-m', str(timeout),
                           '-o', '/dev/null', '-w', '%{http_code}',
                           '-A', 'AI-Science-Tracker-Link-Monitor/1.0', '--', url],
                          capture_output=True, text=True, timeout=timeout + 5).stdout.strip()


def inspect(url, checker=status):
    try:
        code = checker(url)
        if code in ('404', '410'):
            # Confirm missing resources; publisher access blocks are inconclusive.
            confirmation = checker(url)
            if confirmation not in ('404', '410'):
                return {'status': 'uncertain', 'http': code, 'confirmation': confirmation}
            return {'status': 'gone', 'http': confirmation}
        if code.isdigit() and 200 <= int(code) < 300:
            return {'status': 'ok', 'http': code}
        return {'status': 'uncertain', 'http': code}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {'status': 'uncertain', 'http': '000', 'error': type(exc).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--timeout', type=int, default=10)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 16 or args.timeout < 1:
        parser.error('Use 1–16 workers and a positive timeout')
    uses = {}
    for name, fields in FIELDS.items():
        for record in json.loads((args.root / 'data' / f'{name}.json').read_text()):
            for field in fields:
                if record.get(field):
                    uses.setdefault(record[field], []).append(f"{name}:{record['id']}:{field}")
            for url in (record.get('evidence') or {}).get('evidence_urls') or []:
                uses.setdefault(url, []).append(f"{name}:{record['id']}:evidence_urls")
    with ThreadPoolExecutor(args.workers) as pool:
        codes = dict(zip(uses, pool.map(lambda url: inspect(url, lambda value: status(value, args.timeout)), uses)))
    gone = {u: c for u, c in codes.items() if c['status'] == 'gone'}
    uncertain = sum(c['status'] == 'uncertain' for c in codes.values())
    for url, result in sorted(gone.items()):
        print(result['http'], url, *uses[url], sep='\n  ')
    print(f'{len(gone)} confirmed missing, {uncertain} inconclusive, {len(codes)} unique links checked')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'total': len(codes), 'gone': len(gone), 'uncertain': uncertain,
            'links': [{'url': url, 'uses': uses[url], **result} for url, result in sorted(codes.items())],
        }, indent=2) + '\n')
    return 1 if gone else 0


if __name__ == '__main__':
    sys.exit(main())
