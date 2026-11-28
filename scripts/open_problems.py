"""Track open problems attacked by AI agents on lefttosolve.com and pequalnp.com.

Usage:
  python3 scripts/open_problems.py --fetch   # download both sources, update data/open-problems.json, build the page
  python3 scripts/open_problems.py           # build open-problems.html from the stored JSON (called by generate_share.py)

The sources' own checkers (the Lean kernel) decide what counts; we copy their public status, not verify it.
"""
import json, re, sys, urllib.request
from datetime import date, datetime, timezone
from html import escape as esc
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DATA = 'data/open-problems.json'
SITE = 'https://aisciencetracker.org/'
UA = 'AIScienceTracker/1.0 (+https://aisciencetracker.org/open-problems.html)'
NAME = 'Open math problems solved by AI agents'
TITLE = NAME + ' · AI Science Tracker'
DESCRIPTION = ('Open math problems settled, formalized or refuted by AI agents on Left to Solve and '
               'the public P vs NP attempt, tracked every 3 hours from their Lean checkers.')
# Labels follow lefttosolve's own lib/outcome.ts, so nothing reads as more solved than the source says.
OUTCOME = {'open': 'Open problem solved', 'pending': 'Statement being verified', 'known': 'Known result formalized',
           'misstated': 'Misstated version', 'warmup': 'Exercise'}
HISTORY_DAYS = 3650


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def gh_url(u):
    """Keep only GitHub pull-request links (trust boundary: the URL comes from a third party)."""
    return u if isinstance(u, str) and re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+/pull/\d+', u) else None


def build_data(lts_solved, lts_stats, pnp_head, pnp_overview, pnp_papers, previous, now):
    today = now[:10]
    cat = lts_stats['catalog']
    by = lts_solved['byOutcome']
    lts = {'open_problems': cat['open'], 'unformalized': cat['unformalized'], 'new_results': by.get('open', 0),
           'known_formalized': by.get('known', 0), 'pending': by.get('pending', 0),
           'misstated': by.get('misstated', 0), 'exercises': by.get('warmup', 0), 'steps': by.get('step', 0)}
    c = pnp_head['counters']
    pnp = {k: c[k] for k in ('lemmas', 'checked', 'refuted', 'conjecture', 'in_work')}
    pnp['agent_sessions'] = c['agent_sessions_total']
    results = sorted(({'id': x['problem_id'], 'title': x['title'], 'outcome': x['outcome'], 'polarity': x['polarity'],
                       'date': x['created_at'][:10], 'handle': x['handle'], 'agent': x['agent'] or 'unknown', 'model': x['model'] or 'unknown',
                       'pr': gh_url(x['pr_url']), **({'note': x['variantOf']} if x.get('variantOf') else {})}
                      for x in lts_solved['solved'] if x['outcome'] in OUTCOME),
                     key=lambda r: (r['date'], r['id']), reverse=True)
    history = [h for h in previous.get('history', []) if h['date'] != today]
    history.append({'date': today, 'lefttosolve': lts, 'pequalnp': pnp})
    return {
        'about': 'Open problems attacked by AI agents, copied every 3 hours from the public data of lefttosolve.com '
                 '(/api/solved, /api/stats) and pequalnp.com (data.pequalnp.com). Each site decides results with '
                 'its own Lean checker; this file is not an independent verification and does not change the '
                 'discovery catalog counts. Steps of reductions are left out.',
        'updated': today,
        'checked_at': now,
        'sources': {
            'lefttosolve': {'name': 'Left to Solve', 'url': 'https://lefttosolve.com', 'counts': lts,
                            'credit_policy': lts_solved.get('creditPolicy', '')},
            'pequalnp': {'name': 'P = NP ?', 'url': 'https://pequalnp.com', 'problem': 'P versus NP',
                         'status': 'open', 'started': pnp_head['started_at'][:10], 'counts': pnp,
                         'programs': [{'title': p['title'], 'goal': p.get('goal', ''), 'counts': p['counts']}
                                      for p in pnp_overview['programs']],
                         'papers': [{'title': p['title'], 'state': p['state'], 'date': p['released_at'][:10],
                                     'url': p['url']} for p in pnp_papers['papers']]},
        },
        'history': history[-HISTORY_DAYS:],
        'results': results,
    }


def fetch(root=ROOT):
    lts = 'https://lefttosolve.com/api/'
    pnp = 'https://data.pequalnp.com/'
    head = get(pnp + 'head.json')
    path = root / DATA
    previous = json.loads(path.read_text()) if path.exists() else {}
    data = build_data(get(lts + 'solved'), get(lts + 'stats'), head, get(pnp + head['files']['map']),
                      get(pnp + head['files']['papers']), previous, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ'))
    assert data['results'] and data['sources']['lefttosolve']['counts']['open_problems'] > 0, 'empty source data'
    # shortcut: one file with every result; split by month when it passes ~5 MB.
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')


def nice(d):
    return date.fromisoformat(d).strftime('%-d %b %Y')


def n(x):
    return f'{x:,}'


def result_li(r):
    pr = f' · <a href="{esc(r["pr"])}">pull request</a>' if r['pr'] else ''
    note = f' {esc(r["note"])}' if r.get('note') else ''
    return (f'<li><a href="https://lefttosolve.com/p/{quote(r["id"])}">{esc(r["title"])}</a> '
            f'<span class="etich{" ok" if r["outcome"] == "open" else ""}">{OUTCOME[r["outcome"]]}</span> '
            f'{esc(r["polarity"].capitalize())}, <time datetime="{r["date"]}">{nice(r["date"])}</time>, '
            f'@{esc(r["handle"])}{esc(tool(r))}{pr}.{note}</li>')


def tool(r):
    """' with agent (model)', leaving out what the pull request did not declare."""
    if r['agent'] == 'unknown':
        return ''
    return f' with {r["agent"]}' + (f' ({r["model"]})' if r['model'] != 'unknown' else '')


def rows(pairs):
    return ''.join(f'<tr><th scope="row">{esc(k)}</th><td>{n(v)}</td></tr>' for k, v in pairs)


SCRIPT = '''<script>
(() => {
  const OUT = %s, list = document.getElementById("op-results"), more = document.getElementById("op-more"),
    count = document.getElementById("op-count"), q = document.getElementById("op-q"),
    o = document.getElementById("op-outcome"), m = document.getElementById("op-model"), step = 100;
  let all = [], shown = [], limit = step;
  // Declared models are free text upstream, so the filter groups them by family name.
  const FAMILY = {claude: /claude|opus|sonnet|haiku|fable|mythos/i, gpt: /gpt|openai|astra|\bsol\b/i, gemini: /gemini/i,
    grok: /grok/i, deepseek: /deepseek/i};
  const UNDECLARED = /^(unknown|undisclosed|unspecified|default|not reported.*)$/i;
  const inFamily = (r, f) => f === "none" ? UNDECLARED.test(r.model)
    : f === "other" ? !UNDECLARED.test(r.model) && !Object.values(FAMILY).some(x => x.test(r.model)) : FAMILY[f].test(r.model);
  const fmt = d => new Date(d + "T00:00:00Z").toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
  const el = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; };
  function item(r) {
    const li = el("li"), a = el("a", r.title);
    a.href = "https://lefttosolve.com/p/" + encodeURIComponent(r.id);
    const t = el("time", fmt(r.date)); t.dateTime = r.date;
    li.append(a, " ", el("span", OUT[r.outcome], r.outcome === "open" ? "etich ok" : "etich"),
      " " + r.polarity[0].toUpperCase() + r.polarity.slice(1) + ", ", t, ", @" + r.handle + (r.agent === "unknown" ? "" : " with " + r.agent + (r.model === "unknown" ? "" : " (" + r.model + ")")));
    if (r.pr) { const p = el("a", "pull request"); p.href = r.pr; li.append(" · ", p); }
    li.append("." + (r.note ? " " + r.note : ""));
    return li;
  }
  function draw() {
    list.replaceChildren(...shown.slice(0, limit).map(item));
    count.textContent = shown.length ? shown.length.toLocaleString("en-GB") + " of " + all.length.toLocaleString("en-GB") + " results"
      : "No results match these filters.";
    more.hidden = shown.length <= limit;
  }
  function filter() {
    const text = q.value.trim().toLowerCase();
    shown = all.filter(r => (!o.value || r.outcome === o.value) && (!m.value || inFamily(r, m.value)) &&
      (!text || (r.title + " " + r.id + " " + r.handle).toLowerCase().includes(text)));
    const p = new URLSearchParams();
    [["q", q.value.trim()], ["outcome", o.value], ["family", m.value]].forEach(([k, v]) => v && p.set(k, v));
    history.replaceState(null, "", (p.size ? "?" + p : location.pathname) + location.hash);
    limit = step; draw();
  }
  fetch("data/open-problems.json").then(r => r.json()).then(d => {
    all = d.results;
    const p = new URLSearchParams(location.search);  // shareable filters, as on the discovery list
    q.value = p.get("q") || ""; o.value = p.get("outcome") || ""; m.value = p.get("family") || "";
    document.getElementById("op-filters").hidden = false;
    filter();
  }).catch(() => { count.textContent = "The full list could not be loaded; the newest solved open problems are shown."; });
  [q, o, m].forEach(e => e.addEventListener("input", filter));
  document.getElementById("op-reset").addEventListener("click", () => { q.value = o.value = m.value = ""; filter(); });
  more.addEventListener("click", () => { limit += step; draw(); });
})();
</script>
'''


def build(root=ROOT):
    path = root / DATA
    if not path.exists():
        return
    d = json.loads(path.read_text())
    lts, pnp = d['sources']['lefttosolve'], d['sources']['pequalnp']
    lc, pc = lts['counts'], pnp['counts']
    hist = ''.join(f'<tr><th scope="row"><time datetime="{h["date"]}">{nice(h["date"])}</time></th>'
                   f'<td>{n(h["lefttosolve"]["open_problems"])}</td><td>{n(h["lefttosolve"]["new_results"])}</td>'
                   f'<td>{n(h["lefttosolve"]["known_formalized"])}</td><td>{n(h["pequalnp"]["checked"])}</td>'
                   f'<td>{n(h["pequalnp"]["refuted"])}</td></tr>' for h in reversed(d['history']))
    programs = ''.join(f'<tr><th scope="row">{esc(p["title"])}</th><td>{n(p["counts"].get("checked", 0))}</td>'
                       f'<td>{n(p["counts"].get("conjecture", 0))}</td><td>{n(p["counts"].get("refuted", 0))}</td></tr>'
                       for p in pnp['programs'])
    papers = ''.join(f'<li><a href="{esc(p["url"])}">{esc(p["title"])}</a>, {esc(p["state"])} '
                     f'<time datetime="{p["date"]}">{nice(p["date"])}</time></li>' for p in pnp['papers'])
    checked = d.get('checked_at', d['updated'] + 'T00:00Z')
    days = {}
    for r in d['results']:
        days.setdefault(r['date'], dict.fromkeys(OUTCOME, 0))[r['outcome']] += 1
    per_day = ''.join(f'<tr><th scope="row"><time datetime="{k}">{nice(k)}</time></th>' + ''.join(f'<td>{n(v)}</td>' for v in c.values()) + '</tr>'
                      for k, c in sorted(days.items(), reverse=True))
    newest = ''.join(result_li(r) for r in [r for r in d['results'] if r['outcome'] == 'open'][:50])
    options = ''.join(f'<option value="{k}">{v}</option>' for k, v in OUTCOME.items())
    body = f'''<section class="banda banda-bassa" aria-labelledby="titolo-pagina">
  <div class="wrap">
    <h1 id="titolo-pagina">Open problems attacked by AI agents</h1>
    <p class="lead">A continuous record of open problems settled, formalized or refuted by AI agents on <a href="{lts["url"]}">Left to Solve</a> and the public <a href="{pnp["url"]}">P vs NP</a> attempt. A Lean proof checker, not a person, decides each result.</p>
  </div>
</section>

<main class="wrap prosa">
  <section aria-labelledby="the-sites">
    <h2 id="the-sites">What the two sites do</h2>
    <div class="pannelli">
      <section class="pannello" aria-labelledby="about-lts">
        <h3 id="about-lts"><a href="{lts["url"]}">Left to Solve</a></h3>
        <p class="descr">A public catalog of open math problems for AI agents.</p>
        <p>It lists {n(lc["open_problems"] + lc["unformalized"])} open problems, from Erdős problems and OEIS conjectures to the Millennium Prize list; {n(lc["open_problems"])} are stated exactly in Lean 4, most from Google DeepMind's formal-conjectures. Anyone can point an AI coding agent at a problem. The agent works on the owner's machine and sends a proof or a disproof as a GitHub pull request.</p>
        <p>The Lean kernel decides: a proof counts only with no gaps and no extra axioms. Credit goes to the GitHub author, with the agent and model they declare. A proof of an open problem counts as solved only after the site checks that the formal statement says what the original problem says.</p>
      </section>
      <section class="pannello" aria-labelledby="about-pnp">
        <h3 id="about-pnp"><a href="{pnp["url"]}">P = NP ?</a></h3>
        <p class="descr">A public attempt on one problem: P versus NP.</p>
        <p>Since <time datetime="{pnp["started"]}">{nice(pnp["started"])}</time> a fleet of AI agents has split the attack into small units of work, each one exact statement in Lean 4, grouped in research programs such as circuit lower bounds, proof complexity and meta-complexity. Outside contributors can connect their own agents.</p>
        <p>A statement counts only when the Lean checker accepts its proof; a checked counterexample marks it refuted. The proofs are public in <a href="https://github.com/open-goat/pequalnp-proofs">open-goat/pequalnp-proofs</a>. Checked statements are steps, not a solution: P versus NP is still open.</p>
      </section>
    </div>
  </section>

  <section aria-labelledby="standing">
    <h2 id="standing">Where things stand</h2>
    <p>Last checked <time datetime="{checked}">{nice(checked[:10])}, {checked[11:16]} UTC</time>, every 3 hours, from each site's public data. Data: <a href="{DATA}">open-problems.json</a>.</p>
    <div class="pannelli">
      <section class="pannello" aria-labelledby="op-lts">
        <h3 id="op-lts"><a href="{lts["url"]}">Left to Solve</a></h3>
        <p class="descr">Open math problems stated in Lean 4, from Erdős problems, the OEIS and the Millennium list.</p>
        <table class="tab-mini"><tbody>{rows([("Open problems stated in Lean", lc["open_problems"]), ("Open problems without a Lean statement yet", lc["unformalized"]), ("Open problems solved", lc["new_results"]), ("Known results formalized", lc["known_formalized"]), ("Proofs whose statement is being verified", lc["pending"]), ("Proofs of misstated versions", lc["misstated"])])}</tbody></table>
      </section>
      <section class="pannello" aria-labelledby="op-pnp">
        <h3 id="op-pnp"><a href="{pnp["url"]}">P = NP ?</a></h3>
        <p class="descr">P versus NP is still open. Agents split the attack into Lean statements (lemmas) since <time datetime="{pnp["started"]}">{nice(pnp["started"])}</time>.</p>
        <table class="tab-mini"><tbody>{rows([("Statements proposed", pc["lemmas"]), ("Checked by Lean", pc["checked"]), ("Refuted", pc["refuted"]), ("Open conjectures", pc["conjecture"]), ("In work now", pc["in_work"]), ("Agent sessions", pc["agent_sessions"])])}</tbody></table>
      </section>
    </div>
  </section>

  <section aria-labelledby="by-day">
    <h2 id="by-day">Day by day</h2>
    <p>Results accepted on Left to Solve each day, by outcome as classified at the last check: a proof whose statement is being verified later moves to solved or misstated.</p>
    <div class="tabella-scorre"><table class="tab-mini"><thead><tr><th scope="col">Date</th>{"".join(f'<th scope="col">{v}</th>' for v in OUTCOME.values())}</tr></thead><tbody>{per_day}</tbody></table></div>
    <h3>Totals at each check</h3>
    <p>The last check of each day, so the record continues even when a source changes its own pages.</p>
    <div class="tabella-scorre"><table class="tab-mini"><thead><tr><th scope="col">Date</th><th scope="col">Open (Left to Solve)</th><th scope="col">Open problems solved</th><th scope="col">Known formalized</th><th scope="col">P vs NP checked</th><th scope="col">P vs NP refuted</th></tr></thead><tbody>{hist}</tbody></table></div>
  </section>

  <section aria-labelledby="pnp-programs">
    <h2 id="pnp-programs">P versus NP, by program</h2>
    <table class="tab-mini"><thead><tr><th scope="col">Program</th><th scope="col">Checked</th><th scope="col">Open conjectures</th><th scope="col">Refuted</th></tr></thead><tbody>{programs}</tbody></table>
    <h3>Papers written up from checked statements</h3>
    <ul>{papers or "<li>None yet.</li>"}</ul>
  </section>

  <section aria-labelledby="results">
    <h2 id="results">All results on Left to Solve</h2>
    <p>Each accepted pull request, newest first, as the site credits it: the GitHub author of the pull request, with the agent and model they declared. Steps of larger reductions are left out. </p>
    <ul>
      <li><strong>Open problem solved</strong>: nobody had a proof before; Lean accepted a proof or a disproof, and the site checked that the formal statement matches the problem.</li>
      <li><strong>Statement being verified</strong>: Lean accepted the proof, but the formal statement is still being checked against the original problem.</li>
      <li><strong>Known result formalized</strong>: a result already settled in the literature, now proved in Lean.</li>
      <li><strong>Misstated version</strong>: the proof is correct for what was written, but the statement did not say what the problem says; the problem is not solved.</li>
      <li><strong>Exercise</strong>: a warm-up task.</li>
    </ul>
    <p>Some entries are special cases of a larger problem, which may still be open; the note on each entry says so.</p>
    <div class="filtri" id="op-filters" hidden>
      <div class="campi">
        <input type="search" id="op-q" aria-label="Search results" placeholder="Search title, problem or handle">
        <select id="op-outcome" aria-label="Outcome"><option value="">All outcomes</option>{options}</select>
        <select id="op-model" aria-label="Model family"><option value="">All models</option><option value="claude">Claude</option><option value="gpt">GPT</option><option value="gemini">Gemini</option><option value="grok">Grok</option><option value="deepseek">DeepSeek</option><option value="other">Other models</option><option value="none">Model not declared</option></select>
        <button type="button" id="op-reset">Reset</button>
      </div>
    </div>
    <p id="op-count" aria-live="polite">Newest open problems solved.</p>
    <ul id="op-results">{newest}</ul>
    <p><button type="button" class="badge" id="op-more" hidden>Show more</button></p>
  </section>

  <section aria-labelledby="sources">
    <h2 id="sources">Sources and limits</h2>
    <p>Counts and results are copied from <a href="https://lefttosolve.com/api/solved">lefttosolve.com</a> and <a href="https://pequalnp.com">pequalnp.com</a> (proofs in <a href="https://github.com/lefttosolve2/open-math-agents">lefttosolve2/open-math-agents</a> and <a href="https://github.com/open-goat/pequalnp-proofs">open-goat/pequalnp-proofs</a>). We do not check the proofs ourselves. A Lean proof shows that a formal statement holds; it does not show that the statement matches the original problem, which is why some are later marked misstated. These results are tracked apart from the discovery catalog and do not change its counts.</p>
  </section>
</main>
''' + SCRIPT % json.dumps(OUTCOME)
    page = (root / 'contact.html').read_text()
    page = re.sub(r'<section class="banda.*?</main>\n', lambda m: body, page, count=1, flags=re.S)
    page = re.sub(r'<link rel="alternate" hreflang=[^>]*>\n|<meta property="og:locale:alternate"[^>]*>\n', '', page)
    page = page.replace('<title>Contact · AI Science Tracker</title>', f'<title>{TITLE}</title>')
    page = re.sub(r'(<meta (?:name|property)="(?:description|og:description|twitter:description)" content=")[^"]*', lambda m: m.group(1) + esc(DESCRIPTION), page)
    page = re.sub(r'(<meta (?:name|property)="(?:og:title|twitter:title)" content=")[^"]*', lambda m: m.group(1) + esc(TITLE), page)
    page = page.replace(f'{SITE}contact.html', f'{SITE}open-problems.html')
    page = page.replace('<a href="open-problems.html">', '<a href="open-problems.html" aria-current="page">', 1)
    import generate_share as gs
    ld = gs.jsonld({'@context': 'https://schema.org/', '@type': 'CollectionPage', 'name': NAME, 'description': DESCRIPTION,
                    'url': SITE + 'open-problems.html', 'inLanguage': 'en', 'dateModified': d['updated'],
                    'creator': gs.CREATOR, 'publisher': gs.PUBLISHER, 'breadcrumb': gs.breadcrumb(NAME, 'open-problems.html'),
                    'isBasedOn': [lts['url'], pnp['url']], 'about': [{'@type': 'Thing', 'name': 'Open problems in mathematics'},
                                                                      {'@type': 'Thing', 'name': 'P versus NP problem'}]})
    page = page.replace('</head>', f'<link rel="alternate" type="application/json" href="{SITE}{DATA}">\n{ld}\n</head>', 1)
    assert 'Contact · AI' not in page and 'contact-privacy' not in page, 'frame substitution failed'
    (root / 'open-problems.html').write_text(page)


if __name__ == '__main__':
    if '--fetch' in sys.argv:
        fetch()
    build()
