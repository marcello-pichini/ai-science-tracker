"""Build claims.html from data/claims.json, reusing the page frame of contact.html.

Usage: python3 scripts/claims/generate_claims.py
"""
import json, re
from datetime import date
from html import escape as esc
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
SITE = 'https://aisciencetracker.org/'
REPO = 'https://github.com/marcello-pichini/ai-science-tracker'
TITLE = 'Open problems to claim · AI Science Tracker'
DESCRIPTION = ('Open problems left by AI discoveries in the catalog, each with a public checker. '
               'Claim one on GitHub, submit a result and let the checker decide.')
STATUS = {'open': 'Open', 'claimed': 'Claimed', 'submitted': 'Submitted, being checked', 'solved': 'Solved', 'retired': 'Retired'}
REASON = {'no_improvement': 'no improvement found', 'out_of_time': 'out of time', 'too_hard': 'too hard',
          'statement_seems_false': 'statement seems false', 'other': 'other'}


def nice(d):
    return date.fromisoformat(d).strftime('%-d %b %Y')


def claim_html(c, titles):
    parent = c['parent_discovery_id']
    sources = ''.join(f'<li><a href="{esc(s["url"])}">{esc(s["label"])}</a>'
                      + (f', {nice(s["date"])}' if s.get('date') else '')
                      + (f', checked {nice(s["checked"])}' if s.get('checked') else '') + '</li>'
                      for s in c['baseline']['sources'])
    attempts = ''.join(
        f'<li><time datetime="{esc(a["date"])}">{nice(a["date"])}</time>, '
        f'<a href="https://github.com/{quote(a["handle"])}">@{esc(a["handle"])}</a> with {esc(a["agent"])} ({esc(a["model"])}): '
        f'{esc(a["outcome"])}{", " + REASON[a["reason"]] if a.get("reason") else ""}. {esc(a["summary"])}</li>'
        for a in c['attempts']) or '<li>No recorded attempts yet.</li>'
    claim_url = f'{REPO}/issues/new?template=claim.yml&title={quote("Claim: " + c["id"])}&claim={quote(c["id"])}'
    live = f'{REPO}/issues?q=' + quote(f'is:issue label:claim in:title {c["id"]}')
    tag = 'etich ok' if c['status'] == 'open' else 'etich'
    return f'''  <section class="pannello" id="{esc(c["id"])}" aria-labelledby="{esc(c["id"])}-title">
    <h3 id="{esc(c["id"])}-title">{esc(c["title"])}</h3>
    <p><span class="{tag}">{STATUS[c["status"]]}</span> From the discovery <a href="share/{quote(parent)}.html">{esc(titles[parent])}</a>.</p>
    <p>{esc(c["statement"])}</p>
    <h4>What counts</h4>
    <p>{esc(c["target"]["format"])}</p>
    <p>Baseline: {esc(c["baseline"]["summary"])}</p>
    <ul>{sources}</ul>
    <p class="descr">{esc(c["caveat"])}</p>
    <h4>Attempts</h4>
    <ul>{attempts}</ul>
    <p><a class="badge" href="{esc(claim_url)}">Claim this problem</a> <a href="{esc(live)}">See current claims on GitHub</a></p>
  </section>
'''


def build(root=ROOT):
    if not (root / 'data/claims.json').exists():
        return
    data = json.loads((root / 'data/claims.json').read_text())
    titles = {d['id']: d['title'] for d in json.loads((root / 'data/discoveries.json').read_text())}
    n_open = sum(c['status'] == 'open' for c in data['claims'])
    body = f'''<section class="banda banda-bassa" aria-labelledby="titolo-pagina">
  <div class="wrap">
    <h1 id="titolo-pagina">Open problems to claim</h1>
    <p class="lead">Concrete next steps left by AI discoveries in the catalog. Anyone can take one, and a public checker decides.</p>
  </div>
</section>

<main class="wrap prosa">
  <section aria-labelledby="how-it-works">
    <h2 id="how-it-works">How it works</h2>
    <ol>
      <li>Pick a problem below and open a claim issue on GitHub. One problem per issue. A claim lapses after 30 days without activity, so others can take it.</li>
      <li>Work with any method and any tools. Say which AI agent and model you used, if any.</li>
      <li>Open a pull request that adds your file under <code>claims/submissions/PROBLEM-ID/</code>. The <a href="{REPO}/blob/main/scripts/claims/verify.py">public checker</a> runs on it and reports the result in the pull request.</li>
      <li>A verified result beats the baseline recorded here. A maintainer then checks the literature before marking the problem solved. Credit goes to the GitHub author of the pull request.</li>
    </ol>
    <p>Failed attempts stay listed with their reason, so the next person does not repeat them. {n_open} of {len(data["claims"])} problems are open. List updated <time datetime="{data["updated"]}">{nice(data["updated"])}</time>. Data: <a href="data/claims.json">claims.json</a>. Results of AI agents on other open problem trackers are in <a href="open-problems.html">Open problems attacked by AI agents</a>.</p>
  </section>
  <section aria-labelledby="problems">
    <h2 id="problems">Problems</h2>
    <div class="pannelli">
{"".join(claim_html(c, titles) for c in data["claims"])}    </div>
  </section>
</main>
'''
    page = (root / 'contact.html').read_text()
    page = re.sub(r'<section class="banda.*?</main>\n', lambda m: body, page, count=1, flags=re.S)
    page = re.sub(r'<link rel="alternate" hreflang=[^>]*>\n|<meta property="og:locale:alternate"[^>]*>\n', '', page)
    page = page.replace('<title>Contact · AI Science Tracker</title>', f'<title>{TITLE}</title>')
    page = re.sub(r'(<meta (?:name|property)="(?:description|og:description|twitter:description)" content=")[^"]*', lambda m: m.group(1) + esc(DESCRIPTION), page)
    page = re.sub(r'(<meta (?:name|property)="(?:og:title|twitter:title)" content=")[^"]*', lambda m: m.group(1) + esc(TITLE), page)
    page = page.replace(f'{SITE}contact.html', f'{SITE}claims.html')
    assert 'Contact · AI' not in page and 'contact-privacy' not in page, 'frame substitution failed'
    (root / 'claims.html').write_text(page)


if __name__ == '__main__':
    build()
