#!/usr/bin/env python3
"""Notify IndexNow (Bing, Yandex, Seznam, Naver) of pages changed between two commits.

Usage: indexnow.py BASE_SHA HEAD_SHA   (the key file <key>.txt sits in the site root)
"""
import json, re, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = 'aisciencetracker.org'
KEY = next(p.stem for p in ROOT.glob('*.txt') if re.fullmatch(r'[0-9a-f]{32}', p.stem))


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def substantive(text):
    # Regeneration rewrites every page's snapshot hash and catalog counts; those alone are not worth a recrawl.
    text = re.sub(r'data-page-snapshot="[0-9a-f]+"|\?v=[0-9a-f]+', '', text)  # asset cache-busting hashes too
    return re.sub(r'\d+', '0', text)


def changed_urls(base, head):
    added = set(git('diff', '--name-only', '--diff-filter=A', base, head).split())
    urls = []
    for f in git('diff', '--name-only', '--diff-filter=AM', base, head).split():
        if not f.endswith('.html') or f == '404.html':
            continue
        new = git('show', f'{head}:{f}')
        if 'http-equiv="refresh"' in new[:2000]:
            continue  # redirect stubs are not indexable
        if f not in added and substantive(git('show', f'{base}:{f}')) == substantive(new):
            continue
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
    req = urllib.request.Request('https://www.bing.com/indexnow', body,
                                 {'Content-Type': 'application/json; charset=utf-8'})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f'IndexNow: {len(urls)} URLs, HTTP {r.status}')


if __name__ == '__main__':
    main(*sys.argv[1:3])
