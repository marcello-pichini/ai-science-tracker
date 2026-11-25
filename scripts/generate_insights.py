#!/usr/bin/env python3
"""Generate insights.html: six static charts about the catalog, each with a data table.

Every figure is plain HTML and CSS produced from data/discoveries.json, data/models.json and
data/plain-language.json (nothing is typed by hand except the editorial rules below), so the
page is deterministic: the "data as of" date is the newest added_date, never the clock.

Usage: python3 scripts/generate_insights.py   (generate_share.main() calls write_insights too)
"""
import hashlib
import html
import json
import math
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_levels  # noqa: E402
import generate_share as gs  # noqa: E402
from entities import organization as canonical_organization  # noqa: E402
from import_model_progress import lab_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PATH = 'insights.html'
URL = gs.BASE + PATH
TITLE = 'Insights: how AI is used in science'
LEAD = ('What does the catalog say about how AI is used in science? '
        '<b>Seven charts you can read in a minute and share</b>, each with its caveat.')
DESCRIPTION = ('Seven charts from the AI Science Tracker catalog: AI labs, landmark results, subjects, organizations, '
               'kinds of AI, models and years, each with its caveat.')
ASSISTANT_FAMILIES = ['gpt4', 'claude', 'gemini', 'gpt5', 'gpt6']
SCIENCE_FAMILIES = ['alphafold', 'esm', 'rfdiffusion', 'alphafold3']
TOPIC_LIMIT = 12
LAB_LIMIT = 8
FIELD_LIMIT = 8
# Family -> lab, used ONLY when data/models.json gives the family no lab (these have no Epoch rows).
# Each entry was checked: the family has no lab there and a linked discovery names the lab as its organization.
FAMILY_LAB = {
    'alphaevolve': 'Google DeepMind', 'alphagenome': 'Google DeepMind', 'alphaproof': 'Google DeepMind',
    'alphadev': 'Google DeepMind', 'alphaqubit': 'Google DeepMind',
    'mattergen': 'Microsoft', 'mattersim': 'Microsoft', 'aurora': 'Microsoft',
    'corrdiff': 'NVIDIA',
}
# Daily preprint searches started this year; earlier years were collected retrospectively.
COLLECTION_CHANGE_YEAR = 2026

# Subject keywords, matched with word boundaries on title + summary (one entry may match several).
TOPICS = OrderedDict([
    ('Cancer', r'cancers?|tumou?rs?|carcinoma|oncolog\w*|leukemia|lymphoma|glioma|melanoma'),
    ('Heart and stroke', r'cardi\w+|heart|stroke|coronary|atrial'),
    ('Brain and mental health', r'alzheimer\w*|dementia|parkinson\w*|depression|schizophreni\w*|autism|epilep\w+'),
    ('Infections and antibiotics', r'antibiotics?|antimicrobial|bacteri\w+|virus\w*|viral|covid\w*|sars-cov-2|tuberculosis|malaria|sepsis|hiv'),
    ('Diabetes and obesity', r'diabet\w+|obesity|insulin'),
    ('Proteins and drug design', r'proteins?|enzymes?|antibod\w+|peptides?|binders?'),
    ('Genes and DNA', r'genom\w+|genes?|dna|crispr|rna'),
    ('New materials and batteries', r'batter\w+|catalysts?|alloys?|crystals?|polymers?|superconduct\w+|perovskites?'),
    ('Weather, climate and Earth', r'weather|climate|forecasts?|earthquakes?|floods?|wildfires?|seismic'),
    ('Space', r'galax\w+|exoplanets?|planets?|stars?|pulsars?|telescopes?|gravitational'),
    ('Mathematics', r'theorems?|conjectures?|lemmas?|mathematic\w*|combinatori\w+'),
    ('Ageing', r'aging|ageing|longevity'),
])

# Kind of AI, first matching rule wins, applied to the free-text ai_technology field.
KINDS = [
    ('AI agents', 'Agents', r'\bagent|agentic|co-?scientist|autonomous (lab|research|discovery)|self-driving lab'),
    ('Language models and transformers', 'Language models', r'transformer|\bllm|large language|qwen|low-rank adaptation|progen|language model|\bgpt|chatgpt|\bbert|claude|gemini|llama|foundation model|protein language|\besm|attention|vision-language|\bvit\b'),
    ('Generative design', 'Generative', r'diffusion|generative|\bgan\b|adversarial|variational auto|\bvae\b|rfdiffusion|proteinmpnn|de novo design|inverse design|normalizing flow|flow matching'),
    ('Graph networks', 'Graph nets', r'graph neural|m3gnet|alignn|schnet|megnet|\bgnn|graph network|message.passing|graph convol|\bgcn\b|graph attention'),
    ('Reinforcement learning', 'Reinforcement', r'reinforcement|\brl\b|alphazero|q-learning|policy gradient|bandit'),
    ('Image and signal networks', 'Image, signal', r'convolution|\bcnn|u-?net|resnet|yolo|efficientnet|densenet|segmentation|image|computer vision|vgg|inception'),
    ('Other deep learning', 'Other deep', r'neural|deep.learning|alphafold|rosettafold|colabfold|esmfold|structure prediction|phasenet|ffnn|feed.?forward|\blstm|\bmlp|perceptron|autoencoder|recurrent|\brnn'),
    ('Classical machine learning', 'Classical ML', r'random forest|xgboost|lightgbm|catboost|gradient.boost|support.vector|radiomic|\bsvm|logistic|lasso|ridge|elastic net|regression|decision tree|k-?means|clustering|bayesian|gaussian process|naive bayes|k-nearest|\bknn|machine.learning|cox|ensemble|classifier|nomogram|shap|boosting|symbolic regression|active learning|\bml\b'),
]
UNCLEAR = ('Other or unclear', 'Unclear')
COMPANY = re.compile(r'\b(Google|DeepMind|OpenAI|Anthropic|Microsoft|Meta|NVIDIA|IBM)\b')
UNIVERSITY = re.compile(r'University|College|Institute of Technology|School|Polytechnic|ETH')
NOT_STATED = re.compile('not stated|not reported', re.I)


def esc(value):
    return html.escape(str(value), quote=True)


def num(n):
    return f'{n:,}'


def entries(n):
    return f'{n:,} ' + ('entry' if n == 1 else 'entries')


def pct(part, whole):
    return round(part * 100 / whole) if whole else 0


def sentence_case(text):
    return text[:1].upper() + text[1:]


def lower_first(text):
    return text if text.startswith('AI ') else text[:1].lower() + text[1:]


def kind_of(text):
    text = (text or '').lower()
    for name, _short, pattern in KINDS:
        if re.search(pattern, text):
            return name
    return UNCLEAR[0]


def joined(names):
    names = list(names)
    return ', '.join(names[:-1]) + ' and ' + names[-1] if len(names) > 1 else ''.join(names)


def level_of(record):
    return evidence_levels.level(record)[0]


def table(caption, head, rows, first_is_header=True):
    """A real data table; the first cell of each row is a row header."""
    cols = ''.join(f'<th scope="col">{esc(h)}</th>' for h in head)
    body = ''
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            text = esc(cell)
            cells.append(f'<th scope="row">{text}</th>' if i == 0 and first_is_header else f'<td>{text}</td>')
        body += f'<tr>{"".join(cells)}</tr>'
    return (f'<details class="insight-data"><summary>View data as a table</summary>'
            f'<div class="insight-scroll" tabindex="0" role="region" aria-label="{esc(caption)}">'
            f'<table class="insight-table"><caption>{esc(caption)}</caption><thead><tr>{cols}</tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>')


class Context:
    def __init__(self, items, models, plain):
        self.items = items
        self.models = models or {}
        self.plain = plain or {}
        self.n = len(items)
        self.by_id = {d['id']: d for d in items}
        dates = [d.get('added_date') for d in items if d.get('added_date')]
        self.as_of = gs.nice_date(max(dates)) if dates else 'not available'

    def source_line(self, extra=''):
        return (f'Source: AI Science Tracker · {num(self.n)} entries · data as of {self.as_of} · CC BY 4.0'
                + extra)


def share_links(slug, text):
    url = f'{URL}#{slug}'
    x = 'https://x.com/intent/post?' + urlencode({'text': text, 'url': url})
    linkedin = 'https://www.linkedin.com/sharing/share-offsite/?url=' + quote(url, safe='')
    return (f'<p class="insight-share"><a href="{esc(x)}" target="_blank" rel="noopener">Share on X</a>'
            f'<a href="{esc(linkedin)}" target="_blank" rel="noopener">Share on LinkedIn</a></p>')


def section(ctx, number, slug, label, tag, title, sub, chart, data, note, source_extra=''):
    return (f'<section class="sez" id="{slug}" aria-labelledby="{slug}-t"><div class="wrap"><article class="insight-card">\n'
            f'<p class="insight-kicker">{number} · {esc(label)} <span class="etich insight-tag">{esc(tag)}</span></p>\n'
            f'<h2 id="{slug}-t">{esc(title)}</h2>\n<p class="insight-sub">{esc(sub)}</p>\n'
            f'<div class="insight-chart">{chart}</div>\n{data}\n'
            f'<p class="insight-note"><b>How to read this:</b> {esc(note)}</p>\n'
            f'<p class="insight-source">{esc(ctx.source_line(source_extra))}</p>\n'
            f'{share_links(slug, title)}\n</article></div></section>')


def labs(ctx):
    """Model families merged per AI lab (lab_for, the model-progress mapping) and crossed with fields."""
    families = {f['id']: f for f in ctx.models.get('families', [])}
    votes = {}
    for m in ctx.models.get('models', []):
        lab = lab_for(m.get('organization') or '')
        if m.get('family') and lab:
            votes.setdefault(m['family'], Counter())[lab] += 1
    lab_ids, unattributed = {}, set()
    for fid, fam in families.items():
        ids = {d for d in fam.get('discoveries', []) if d in ctx.by_id}
        if fid in votes:
            lab = sorted(votes[fid].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            lab_ids.setdefault(lab, set()).update(ids)
        elif fid in FAMILY_LAB:
            lab_ids.setdefault(FAMILY_LAB[fid], set()).update(ids)
        else:
            unattributed |= ids
    excluded = len(unattributed - set().union(*lab_ids.values())) if lab_ids else len(unattributed)
    ranked = sorted(lab_ids.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:LAB_LIMIT]
    field_count = Counter(ctx.by_id[d]['field'] for _l, ids in ranked for d in ids)
    shown = [f for f, _n in sorted(field_count.items(), key=lambda kv: (-kv[1], kv[0]))][:FIELD_LIMIT]
    columns = shown + (['other'] if len(field_count) > len(shown) else [])

    def column(d):
        f = ctx.by_id[d]['field']
        return f if f in shown else 'other'
    cells = {lab: Counter(column(d) for d in ids) for lab, ids in ranked}
    peak = max([c for row in cells.values() for c in row.values()] or [1])
    body, rows = '', []
    for lab, ids in ranked:
        tds = ''.join(
            f'<td title="{esc(lab)}, {esc(c)}: {entries(cells[lab][c])} linked">'
            + (f'<span style="--d:{math.sqrt(cells[lab][c] / peak):.3f}">{cells[lab][c]}</span>' if cells[lab][c] else '') + '</td>'
            for c in columns)
        body += f'<tr><th scope="row">{esc(lab)}</th>{tds}<td class="insight-total">{len(ids)}</td></tr>'
        rows.append([lab] + [str(cells[lab][c]) for c in columns] + [str(len(ids))])
    head = ''.join(f'<th scope="col">{esc(sentence_case(c))}</th>' for c in columns)
    chart = (f'<div class="insight-scroll" tabindex="0" role="img" aria-label="Linked entries per AI lab and field; the data table below has the same numbers">'
             f'<table class="insight-matrix insight-matrix-wide"><thead><tr><th></th>{head}<th scope="col">All</th></tr></thead><tbody>{body}</tbody></table></div>'
             '<p class="insight-legend"><span><i class="insight-key-dot"></i>Circle area = entries linked to the lab’s models in that field</span></p>'
             if ranked else '<p class="insight-empty">No model families are linked to a lab.</p>')
    data = table('Entries linked to each AI lab’s models, by field', ['Lab'] + [sentence_case(c) for c in columns] + ['All'], rows)
    tie = len(ranked) >= 2 and len(ranked[0][1]) == len(ranked[1][1])
    if tie:
        title = f'{ranked[0][0]} and {ranked[1][0]} are linked to the most entries ({len(ranked[0][1])} each)'
        if len(ranked) >= 3:
            title += f'; {ranked[2][0]} follows with {len(ranked[2][1])}'
    elif len(ranked) >= 3:
        title = (f'{ranked[0][0]}’s models are linked to the most entries ({len(ranked[0][1])}); '
                 f'{ranked[1][0]} and {ranked[2][0]} follow with {len(ranked[1][1])} and {len(ranked[2][1])}')
    elif ranked:
        title = f'{ranked[0][0]}’s models are linked to the most entries ({len(ranked[0][1])})'
    else:
        title = 'Entries linked to AI labs’ models'
    return section(ctx, 1, 'labs', 'Which labs', 'Name-based links', title,
                   'Each circle counts the catalog entries linked to a lab’s models, merged across the lab’s model families, in one field. An entry linked to two families of one lab counts once for that lab.',
                   chart, data,
                   f'a link means the lab’s model is named in the result, usually used by other researchers, not that the lab made the discovery. Links are name-based associations, not verified version attribution, and the catalog searched more widely in 2026. Left out: {entries(excluded)} linked to a model family with no lab.',
                   ' · Model data: Epoch AI, CC BY 4.0')


def landmarks(ctx):
    rows = []
    for rid in ctx.plain.get('landmarks') or []:
        record = ctx.by_id.get(rid)
        headline = ((ctx.plain.get('records') or {}).get(rid) or {}).get('headline')
        if record and headline:
            rows.append((record['publication_date'], rid, record, headline))
    rows.sort(key=lambda r: r[0])
    items = ''.join(
        f'<li><time datetime="{esc(date)}">{esc(date[:4])}</time><span class="insight-pin" aria-hidden="true"></span>'
        f'<div><a href="share/{quote(rid)}.html">{esc(headline)}</a>'
        f'<p><span class="etich">{esc(rec["field"])}</span> {evidence_levels.meter_html(rec)}</p></div></li>'
        for date, rid, rec, headline in rows)
    chart = f'<ol class="insight-timeline">{items}</ol>' if rows else '<p class="insight-empty">No landmark entries are selected.</p>'
    data = table('Landmark results', ['Year', 'Result', 'Field', 'How tested'],
                 [(d[:4], h, r['field'], evidence_levels.level(r)[1]) for d, _i, r, h in rows])
    if rows:
        title = f'{len(rows)} landmark results and claims in AI-enabled science, from {rows[0][0][:4]} to {rows[-1][0][:4]}'
    else:
        title = 'Landmark results in AI-enabled science'
    return section(ctx, 2, 'landmarks', 'Landmarks', 'Editorial selection', title,
                   'A short editorial selection of catalog entries, one line each. The small bars show how far each result was tested.',
                   chart, data,
                   'the selection is editorial, not a ranking, and some recent results are claims released by their authors. Each line links to the full record with its caveats.')


def topics(ctx):
    counts = Counter()
    for d in ctx.items:
        text = (d['title'] + ' ' + d.get('summary', '')).lower()
        for name, pattern in TOPICS.items():
            if re.search(r'\b(?:' + pattern + r')\b', text):
                counts[name] += 1
    ranked = sorted(((n, k) for k, n in counts.items() if n), key=lambda r: (-r[0], r[1]))[:TOPIC_LIMIT]
    top = ranked[0][0] if ranked else 0
    label = 'Topics by number of entries: ' + ', '.join(f'{k} {n}' for n, k in ranked)
    bubbles = ''.join(
        f'<div class="insight-bubble{" is-first" if j == 0 else ""}" title="{esc(k)}: {entries(n)}">'
        f'<span style="--d:{math.sqrt(n / top):.3f}">{num(n)}</span><b>{esc(k)}</b></div>'
        for j, (n, k) in enumerate(ranked))
    chart = (f'<div class="insight-bubbles" role="img" aria-label="{esc(label)}">{bubbles}</div>'
             if ranked else '<p class="insight-empty">No subjects matched.</p>')
    data = table('Entries mentioning each subject', ['Subject', 'Entries'], [(k, num(n)) for n, k in ranked])
    if ranked:
        title = f'{ranked[0][1]} is the subject named most often, in {entries(ranked[0][0])}'
        if len(ranked) > 2:
            title += f', followed by {lower_first(ranked[1][1])} ({num(ranked[1][0])}) and {lower_first(ranked[2][1])} ({num(ranked[2][0])})'
    else:
        title = 'Subjects named in catalog entries'
    return section(ctx, 3, 'topics', 'What for', 'Keyword matching', title,
                   'Circle area shows how many catalog entries mention each subject in their title or summary.',
                   chart, data,
                   'subjects are matched by keywords, so one entry can count under several and some are missed. It shows what the catalog covers, not where AI works best.')


def organization_kind(name):
    if COMPANY.search(name):
        return 'AI lab or company'
    if 'Academy' in name:
        return 'Research academy'
    return 'University' if UNIVERSITY.search(name) else 'Research institution'


def who(ctx):
    counts = Counter()
    unstated = 0
    for d in ctx.items:
        names = set()
        for part in d.get('organization', '').split(';'):
            part = part.strip()
            if not part:
                continue
            if NOT_STATED.search(part):
                continue
            row = canonical_organization(part)
            if row['kind'] == 'unknown affiliation':
                continue
            names.add(row['label'])
        if not names:
            unstated += 1
        counts.update(names)
    ranked = sorted(counts.items(), key=lambda r: (-r[1], r[0]))[:10]
    css = {'AI lab or company': 'is-lab', 'Research academy': 'is-academy', 'University': 'is-university',
           'Research institution': 'is-institution'}
    podium = ''.join(
        f'<li class="{css[organization_kind(name)]}"><i>{j + 1}</i><b>{esc(name)}</b>'
        f'<span>{entries(n)} · {organization_kind(name)}</span></li>' for j, (name, n) in enumerate(ranked))
    chart = f'<ol class="insight-podium">{podium}</ol>' if ranked else '<p class="insight-empty">No organizations are named.</p>'
    data = table('Organizations named on the most entries', ['Rank', 'Organization', 'Entries', 'Type'],
                 [(str(j + 1), name, num(n), organization_kind(name)) for j, (name, n) in enumerate(ranked)])
    if len(ranked) >= 3:
        title = (f'{ranked[0][0]}, {ranked[1][0]} and {ranked[2][0]} are named on the most entries, '
                 f'with {num(ranked[0][1])}, {num(ranked[1][1])} and {num(ranked[2][1])}')
    elif ranked:
        title = f'{ranked[0][0]} is named on the most entries, with {num(ranked[0][1])}'
    else:
        title = 'Organizations named on catalog entries'
    return section(ctx, 4, 'who', 'Who', 'Name matching', title,
                   'The ten organizations named on the most catalog entries. An entry with several organizations counts once for each.',
                   chart, data,
                   f'names follow the reviewed alias list and are otherwise matched as written, so departments and hospitals are not rolled up into their institution, and {entries(unstated)} state no affiliation. The ranking can change when names are standardized.')


def kind_of_ai(ctx):
    names = [k[0] for k in KINDS] + [UNCLEAR[0]]
    short = {k[0]: k[1] for k in KINDS}
    short[UNCLEAR[0]] = UNCLEAR[1]
    grid = OrderedDict()
    totals = Counter()
    for d in ctx.items:
        kind = kind_of(d.get('ai_technology'))
        row = grid.setdefault(d['field'], Counter())
        row[kind] += 1
        row['_n'] += 1
        totals[kind] += 1
    fields = sorted(grid, key=lambda f: (-grid[f]['_n'], f))
    kinds = sorted(names[:-1], key=lambda k: (-totals[k], k)) + [UNCLEAR[0]]
    shares = {f: {k: grid[f][k] * 100 / grid[f]['_n'] for k in kinds} for f in fields}
    peak = max([v for f in fields for v in shares[f].values()] or [0])
    leaders = {}
    for f in fields:
        best = max(shares[f][k] for k in kinds[:-1])
        if best > 0:
            leaders[f] = next(k for k in kinds[:-1] if shares[f][k] == best)
    body = ''
    for f in fields:
        cells = ''
        for k in kinds:
            p = shares[f][k]
            cls = ' '.join(c for c in ('is-strong' if peak and p / peak > .55 else '', 'is-leading' if leaders.get(f) == k else '') if c)
            cells += (f'<td{f" class={chr(34)}{cls}{chr(34)}" if cls else ""} style="--v:{(p / peak) if peak else 0:.2f}" '
                      f'title="{esc(f)}, {esc(k)}: {grid[f][k]} of {grid[f]["_n"]}">{p:.0f}</td>')
        body += f'<tr><th scope="row">{esc(sentence_case(f))}</th>{cells}</tr>'
    head = ''.join(f'<th scope="col">{esc(short[k])}</th>' for k in kinds)
    chart = (f'<div class="insight-scroll" tabindex="0" role="img" aria-label="Heat grid of kinds of AI as a percent of each field; the data table below has the same numbers">'
             f'<table class="insight-heat"><thead><tr><th scope="col">% of field</th>{head}</tr></thead><tbody>{body}</tbody></table></div>'
             '<p class="insight-legend"><span><i class="insight-key-lead"></i>Outlined: the field’s most common classified kind</span></p>'
             if fields else '<p class="insight-empty">No entries to classify.</p>')
    data = table('Kind of AI by field, entries and percent of the field',
                 ['Field', 'Entries'] + [short[k] for k in kinds],
                 [[sentence_case(f), num(grid[f]['_n'])] + [f'{grid[f][k]} ({shares[f][k]:.0f}%)' for k in kinds] for f in fields])
    # Title: the kinds that lead in the most fields, each with its largest fields.
    by_kind = OrderedDict()
    for f in fields:
        if f in leaders:
            by_kind.setdefault(leaders[f], []).append(f)
    groups = sorted(by_kind.items(), key=lambda kv: (-sum(grid[f]['_n'] for f in kv[1]), kv[0]))[:2]

    def where(fs):
        shown = fs[:3]
        more = len(fs) - len(shown)
        return ', '.join(shown) + f' and {more} more fields' if more > 0 else joined(shown)
    if groups:
        first = groups[0]
        title = f'Most common kind of AI: {lower_first(first[0])} in {where(first[1])}'
        if len(groups) > 1:
            title += f'; {lower_first(groups[1][0])} in {where(groups[1][1])}'
    else:
        title = 'Kinds of AI by field'
    unclear = pct(totals[UNCLEAR[0]], ctx.n)
    return section(ctx, 5, 'kind-of-ai', 'Which AI', 'Preliminary classification', title,
                   'Each row splits one field’s entries by kind of AI, as a percent of that field. Darker means a larger share; the outlined cell is the field’s most common classified kind.',
                   chart, data,
                   f'kinds come from keyword rules on a free-text field, so about {unclear}% of entries are unclear and a few points of difference are noise.')


def models_section(ctx):
    families = {f['id']: f for f in ctx.models.get('families', [])}
    first = {}
    for m in ctx.models.get('models', []):
        if m.get('family') and m.get('date'):
            first[m['family']] = min(first.get(m['family'], '9999'), m['date'])
    years_all = sorted({d['publication_date'][:4] for d in ctx.items})
    years = [str(y) for y in range(int(years_all[0]), int(years_all[-1]) + 1)] if years_all else []
    groups = [('Built for science', [f for f in SCIENCE_FAMILIES if f in families and f in first]),
              ('General-purpose assistants', [f for f in ASSISTANT_FAMILIES if f in families and f in first])]

    def linked(fid):
        return Counter(ctx.by_id[d]['publication_date'][:4] for d in families[fid]['discoveries'] if d in ctx.by_id)

    def unique(fids, year):
        return len({d for f in fids for d in families[f]['discoveries']
                    if d in ctx.by_id and ctx.by_id[d]['publication_date'][:4] == year})
    peak = max([c for _g, fids in groups for f in fids for c in linked(f).values()] or [1])
    body, rows = '', []
    for label, fids in groups:
        if not fids:
            continue
        body += f'<tr class="insight-group"><th colspan="{len(years) + 2}">{esc(label)}</th></tr>'
        for f in sorted(fids, key=lambda f: (first[f], f)):
            counts = linked(f)
            cells = ''
            for y in years:
                cls = ' '.join(c for c in ('is-release' if y == first[f][:4] else '', 'is-before' if y < first[f][:4] else '') if c)
                inner = f'<span style="--d:{min(1, math.sqrt(counts[y] / peak)):.3f}">{counts[y]}</span>' if counts[y] else ''
                cells += (f'<td{f" class={chr(34)}{cls}{chr(34)}" if cls else ""} '
                          f'title="{esc(families[f]["name"])}, {y}: {entries(counts[y])} linked">{inner}</td>')
            body += f'<tr><th scope="row">{esc(families[f]["name"])}</th>{cells}<td class="insight-total">{sum(counts.values())}</td></tr>'
            rows.append([families[f]['name'], label, first[f]] + [str(counts[y]) for y in years] + [str(sum(counts.values()))])
    head = ''.join(f'<th scope="col">{y}</th>' for y in years)
    chart = (f'<div class="insight-scroll" tabindex="0" role="img" aria-label="Linked entries per model family and publication year; the data table below has the same numbers">'
             f'<table class="insight-matrix"><thead><tr><th></th>{head}<th scope="col">All</th></tr></thead><tbody>{body}</tbody></table></div>'
             '<p class="insight-legend"><span><i class="insight-key-release"></i>Year of first release</span>'
             '<span><i class="insight-key-dot"></i>Circle area = linked entries that year</span></p>'
             if rows else '<p class="insight-empty">No model families with a dated release are linked to entries.</p>')
    data = table('Entries linked to each model family, by publication year',
                 ['Family', 'Group', 'First release'] + years + ['All'], rows)
    science_ids = groups[0][1]
    assistant_ids = groups[1][1]
    # One reference year: the latest whose total is at least half of the previous year's, so a January with a few entries falls back.
    total = Counter(d['publication_date'][:4] for d in ctx.items)
    ref = next((y for y in reversed(years) if 2 * total[y] >= total[str(int(y) - 1)]), None)
    a = unique(assistant_ids, ref) if ref else 0
    b = unique(science_ids, ref) if ref else 0
    if rows and a + b:
        title = (f'In {ref}, {a} entries are linked to general-purpose assistants '
                 f'and {b} to models built for science')
    else:
        title = 'Entries linked to model families, by year'
    return section(ctx, 6, 'which-models', 'Which models', 'Name-based links', title,
                   'Each circle counts the catalog entries linked to a model family in the year the result was published. Shaded cells mark the family’s first release in the Epoch AI data.',
                   chart, data,
                   'links are name-based associations, not proof that a given model version was used, and the catalog searched more widely in the latest year. An entry can count under more than one family.',
                   ' · Model release dates: Epoch AI, CC BY 4.0')


def by_year(ctx):
    per = {}
    for d in ctx.items:
        status = (d.get('evidence') or {}).get('publication_status')
        key = 'peer' if status == 'Peer-reviewed paper' else 'preprint' if status == 'Preprint' else 'other'
        per.setdefault(d['publication_date'][:4], Counter())[key] += 1
    years = [str(y) for y in range(int(min(per)), int(max(per)) + 1)] if per else []
    totals = {y: sum(per.get(y, Counter()).values()) for y in years}
    top = max(totals.values() or [0]) or 1
    cols = ''
    for y in years:
        v = per.get(y, Counter())
        now = y == str(COLLECTION_CHANGE_YEAR)
        stack = ''.join(f'<i class="{k}" style="flex:{v[k]}"></i>' for k in ('other', 'preprint', 'peer') if v[k])
        cols += (f'<div class="insight-col{" is-latest" if now else ""}"><div class="insight-col-area">'
                 f'{"<em>wider collection</em>" if now else ""}<b>{num(totals[y])}</b>'
                 f'<div class="insight-stack" style="--h:{totals[y] * 100 / top:.1f}" '
                 f'title="{y}: {v["peer"]} peer-reviewed, {v["preprint"]} preprints, {v["other"]} other">{stack}</div></div><span>{y}</span></div>')
    chart = ('<p class="insight-legend"><span><i class="peer"></i>Peer-reviewed paper</span><span><i class="preprint"></i>Preprint</span>'
             '<span><i class="other"></i>Announcement or not reported</span>'
             + (f'<span><i class="insight-key-latest"></i>Dashed outline: {COLLECTION_CHANGE_YEAR}, when the catalog started daily preprint searches</span>'
                if str(COLLECTION_CHANGE_YEAR) in years else '') + '</p>'
             f'<div class="insight-cols" style="--n:{len(years)}" role="img" aria-label="Entries per publication year, split by source type; the data table below has the same numbers">{cols}</div>'
             if years else '<p class="insight-empty">No entries.</p>')
    data = table('Entries per publication year, by source type', ['Year', 'Peer-reviewed paper', 'Preprint', 'Announcement or not reported', 'All'],
                 [(y, num(per.get(y, Counter())['peer']), num(per.get(y, Counter())['preprint']), num(per.get(y, Counter())['other']), num(totals[y])) for y in years])
    if years:
        full = [y for y in years if int(y) < COLLECTION_CHANGE_YEAR]
        first_peer = per.get(full[0], Counter())['peer'] if full else 0
        last_peer = per.get(full[-1], Counter())['peer'] if full else 0
        if len(full) >= 3 and first_peer and last_peer > first_peer:
            ratio = last_peer / first_peer
            growth = round((ratio ** (1 / (len(full) - 1)) - 1) * 100)
            title = (f'Peer-reviewed entries in the catalog grew {ratio:.1f}-fold from {full[0]} to {full[-1]}, '
                     f'about {growth}% a year')
            rate = f'the rate uses peer-reviewed entries up to {full[-1]}; '
        else:
            title = f'Catalog entries by publication year, {years[0]} to {years[-1]}'
            rate = ''
    else:
        title, rate = 'Entries by publication year and source type', ''
    return section(ctx, 7, 'by-year', 'Year by year', 'Counts by source type', title,
                   'Entries by the year the result was first published, split by the kind of source the catalog records.',
                   chart, data,
                   f'{rate}from {COLLECTION_CHANGE_YEAR} the catalog also searches preprint servers daily, so later columns are not comparable with earlier ones. '
                   'The current year is incomplete. Counts are catalog entries, not all of science.')


def banner_tiles(ctx):
    steps = [level_of(d) for d in ctx.items]
    new_test, independent = sum(s >= 2 for s in steps), sum(s >= 3 for s in steps)
    tiles = [('Catalog entries', num(ctx.n), ''),
             ('Tested in a new experiment, or stronger', f'{pct(new_test, ctx.n)}%', num(new_test)),
             ('Independently or prospectively checked', f'{pct(independent, ctx.n)}%', num(independent))]
    return ('<dl class="collection-facts insight-facts">' + ''.join(
        f'<div><dt>{esc(t)}</dt><dd>{v}{f" <small>{c}</small>" if c else ""}</dd></div>' for t, v, c in tiles) + '</dl>')


def closing():
    return ('<section class="sez" aria-labelledby="reuse-t"><div class="wrap"><div class="pannello">\n'
            '<h2 id="reuse-t" class="sez-tit">Use these charts</h2>\n'
            '<p>You may reuse and adapt these charts under CC BY 4.0: credit “AI Science Tracker” and link to this page. '
            'Model release data comes from <a href="https://epoch.ai/data/ai-models">Epoch AI</a>, also CC BY 4.0.</p>\n'
            '<p>Figures describe what original sources report and have not been independently verified. '
            '<a href="index.html">Browse the full catalog</a> to see every entry and its source.</p>\n'
            '</div></div></section>')


def render(items, models, plain, root=ROOT):
    ctx = Context(items, models, plain)
    header, footer = gs.site_frame()
    desc = DESCRIPTION
    head = gs.PAGE.split('<body', 1)[0].replace('content="article"', 'content="website"')
    head = head.format_map(_Defaults(title=esc(TITLE), site=gs.SITE, desc=esc(desc), base=gs.BASE, path=PATH,
                                     img='default', imgalt=esc(gs.DEFAULT_ALT),
                                     jsonld=gs.profile_jsonld(TITLE, desc, PATH, page_type='WebPage')))
    css = root / 'styles.css'
    if css.is_file():
        head = head.replace('href="styles.css"', f'href="styles.css?v={hashlib.sha256(css.read_bytes()).hexdigest()[:12]}"')
    i18n = root / 'assets' / 'i18n.css'
    head = head.replace('__I18N_CSS__', 'assets/i18n.css' + (f'?v={hashlib.sha256(i18n.read_bytes()).hexdigest()[:12]}' if i18n.is_file() else ''))
    sections = '\n'.join((labs(ctx), landmarks(ctx), topics(ctx), who(ctx), kind_of_ai(ctx), models_section(ctx), by_year(ctx)))
    page = (f'{head}<body class="static-page">\n{header}\n\n'
            '<section class="banda banda-bassa" aria-labelledby="titolo-pagina">\n  <div class="wrap">\n'
            f'    <h1 id="titolo-pagina">Insights</h1>\n    <p class="lead">{LEAD}</p>\n    {banner_tiles(ctx)}\n  </div>\n</section>\n\n'
            f'<main>\n{sections}\n{closing()}\n</main>\n\n{footer}\n</body>\n</html>\n')
    return '\n'.join(line.rstrip() for line in gs.fit_title(page).splitlines()) + '\n'


class _Defaults(dict):
    def __missing__(self, key):
        return ''


def write_insights(items, models, plain, root=ROOT):
    root = Path(root)
    (root / PATH).write_text(render(items, models, plain, root), encoding='utf-8')


def main():
    items = json.loads((ROOT / 'data/discoveries.json').read_text(encoding='utf-8'))
    models = json.loads((ROOT / 'data/models.json').read_text(encoding='utf-8'))
    plain = gs.usable_plain(json.loads((ROOT / 'data/plain-language.json').read_text(encoding='utf-8')), items)
    write_insights(items, models, plain)


if __name__ == '__main__':
    main()
