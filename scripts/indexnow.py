#!/usr/bin/env python3
"""Notify IndexNow (Bing, Yandex, Seznam, Naver) of pages changed between two commits.

Usage: indexnow.py BASE_SHA HEAD_SHA   (the key file <key>.txt sits in the site root)
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = 'aisciencetracker.org'
KEY = next(p.stem for p in ROOT.glob('*.txt') if re.fullmatch(r'[0-9a-f]{32}', p.stem))


def changed_urls(base, head):
    out = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=AM', base, head],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    urls = []
    for f in out:
        if not f.endswith('.html') or f == '404.html':
            continue
        if 'http-equiv="refresh"' in (ROOT / f).read_text(errors='ignore')[:2000]:
            continue  # redirect stubs are not indexable
        path = re.sub(r'(^|/)index\.html$', r'\1', f)
        urls.append(f'https://{HOST}/{path}')
    return sorted(set(urls))


def main(base, head):
    urls = changed_urls(base, head)[:10000]  # IndexNow limit per request
    if not urls:
        print('No changed pages.')
        return
    body = json.dumps({'host': HOST, 'key': KEY, 'keyLocation': f'https://{HOST}/{KEY}.txt',
                       'urlList': urls}).encode()
    req = urllib.request.Request('https://api.indexnow.org/indexnow', body,
                                 {'Content-Type': 'application/json; charset=utf-8'})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f'IndexNow: {len(urls)} URLs, HTTP {r.status}')


if __name__ == '__main__':
    main(*sys.argv[1:3])
