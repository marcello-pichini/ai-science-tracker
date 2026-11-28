#!/usr/bin/env python3
"""Publish the global vulnerability dataset files as a new Zenodo version.

Usage: ZENODO_TOKEN=... zenodo_upload.py DIR VERSION
The first run creates the record; later runs add a version to the record whose title matches TITLE.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = 'https://zenodo.org/api'
TITLE = 'Global Vulnerability Dataset'


def call(method, url, body=None, data=None, size=None):
    headers = {'Authorization': f'Bearer {os.environ["ZENODO_TOKEN"]}'}
    if body is not None:
        data, headers['Content-Type'] = json.dumps(body).encode(), 'application/json'
    if size is not None:
        headers['Content-Type'], headers['Content-Length'] = 'application/octet-stream', str(size)
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=3600) as r:
        text = r.read()
    return json.loads(text) if text else {}


def metadata(version):
    sources = 'https://github.com/marcello-pichini/ai-science-tracker/blob/main/docs/vulnerability-sources.md'
    schema = 'https://github.com/marcello-pichini/ai-science-tracker/blob/main/docs/vulnerability-global-schema.md'
    return {'metadata': {
        'title': TITLE, 'upload_type': 'dataset', 'version': version, 'access_right': 'open', 'license': 'other-open',
        'creators': [{'name': 'Pichini, Marcello', 'orcid': '0009-0007-4958-371X'}],
        'keywords': ['vulnerabilities', 'CVE', 'cybersecurity', 'security advisories', 'dataset'],
        'description': ('Every public CVE and open-source advisory, one record per vulnerability, joined from more than '
                        'twenty public sources with every source\'s data kept and attributed. Each field keeps its '
                        f'source\'s terms, listed in <a href="{sources}">the sources and reuse terms</a>; fields derived '
                        'by AI Science Tracker are CC BY 4.0. This product uses the NVD API but is not endorsed or '
                        f'certified by the NVD. Field reference: <a href="{schema}">schema</a>.'),
        'related_identifiers': [{'identifier': 'https://aisciencetracker.org/security.html', 'relation': 'isDocumentedBy',
                                 'scheme': 'url', 'resource_type': 'other'}]}}


def main(folder, version):
    found = call('GET', f'{API}/deposit/depositions?' + urllib.parse.urlencode({'q': f'title:"{TITLE}"', 'size': 50}))
    found = [d for d in found if d.get('title') == TITLE and d.get('submitted')]
    if found:
        draft = call('POST', f'{API}/deposit/depositions/{found[0]["id"]}/actions/newversion')
        draft = call('GET', draft['links']['latest_draft'])
        for f in draft.get('files', []):
            call('DELETE', f'{API}/deposit/depositions/{draft["id"]}/files/{f["id"]}')
    else:
        draft = call('POST', f'{API}/deposit/depositions', body={})
    for path in sorted(Path(folder).iterdir()):
        if path.is_file():
            with path.open('rb') as fh:
                call('PUT', f'{draft["links"]["bucket"]}/{urllib.parse.quote(path.name)}', data=fh, size=path.stat().st_size)
            print('uploaded', path.name)
    call('PUT', f'{API}/deposit/depositions/{draft["id"]}', body=metadata(version))
    done = call('POST', f'{API}/deposit/depositions/{draft["id"]}/actions/publish')
    print('published', done.get('doi_url') or done.get('links', {}).get('record_html'))


if __name__ == '__main__':
    if len(sys.argv) != 3 or not os.environ.get('ZENODO_TOKEN'):
        sys.exit(__doc__)
    main(*sys.argv[1:])
