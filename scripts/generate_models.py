"""Generate data/models.json from Epoch AI CSV and data/discoveries.json.

Source: Epoch AI, Data on AI models, CC BY 4.0.
Place the downloaded CSV at work/epoch/notable_ai_models.csv, then run from
this repository root: python3 scripts/generate_models.py
"""
import csv, json, re, datetime, hashlib, math, os, tempfile
from pathlib import Path

CSV = 'work/epoch/notable_ai_models.csv'
DISCOVERIES = 'data/discoveries.json'
OUT = 'data/models.json'

LAB = re.compile(r'^(openai|google deepmind|deepmind|google|google research|google brain|google cloud|google ai|anthropic|microsoft|microsoft research|microsoft research asia|meta ai|meta|facebook ai research|nvidia|baidu|alibaba|bytedance|deepseek|tencent|huawei|mistral ai|xai|ibm|amazon|z\.ai|moonshot|minimax|evolutionaryscale|apple|cohere)', re.I)

from model_families import FAMILIES, discovery_links

def num(s):
    if not s or not s.strip():
        return None
    value = float(s)
    if not math.isfinite(value):
        raise ValueError(f'Non-finite numeric value: {s!r}')
    return value

with open(CSV, encoding='utf-8') as source:
    reader = csv.DictReader(source)
    required = {'Model', 'Organization', 'Publication date'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('Epoch CSV is missing required headers')
    rows = list(reader)
discoveries = json.load(open(DISCOVERIES, encoding='utf-8'))


models = []
for r in rows:
    name = (r.get('Model') or '').strip()
    org  = (r.get('Organization') or '').strip()
    date = (r.get('Publication date') or '').strip()
    if not name or not date:
        continue
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        raise ValueError(f'Invalid publication date: {date!r}')
    datetime.date.fromisoformat(date)
    fam = next((f[0] for f in FAMILIES if re.search(f[2], name, re.I)), None)
    recent_lab = date >= '2020-01-01' and LAB.search(org)
    if not (recent_lab or fam):
        continue
    link = (r.get('Link') or '').strip().split(' ')[0].rstrip(',;')
    if re.match(r'^arxiv\.org/abs/[^\s]+$', link, re.I):
        link = 'https://' + link
    compute = (r.get('Training compute (FLOP)') or '').strip()
    num(compute)
    models.append({
        'name': name,
        'organization': org,
        'date': date,
        'domain': (r.get('Domain') or '').strip(),
        'parameters': num(r.get('Parameters','')),
        'compute_flop': compute,
        'access': (r.get('Model accessibility') or '').strip(),
        'frontier': (r.get('Frontier model') or '').strip().lower() == 'true',
        'link': link,
        'family': fam,
    })
if not models:
    raise ValueError('Epoch CSV produced no eligible models')
models.sort(key=lambda m: m['date'], reverse=True)

families = []
links = discovery_links(discoveries)
linked = set()
for fid, name, re_mod, re_sco in FAMILIES:
    sc = links[fid]
    mods = [m['name'] for m in models if m['family'] == fid]
    if not sc and not mods:
        continue
    linked.update(sc)
    families.append({'id': fid, 'name': name, 'discoveries': sc, 'models': mods,
                     'discovery_count': len(sc), 'model_count': len(mods)})
families.sort(key=lambda f: (-f['discovery_count'], f['name'].lower()))

out = {
 'generated': datetime.date.today().isoformat(),
 'source': {
   'name': 'Epoch AI — Data on AI models (notable models)',
   'url': 'https://epoch.ai/data/ai-models',
   'license': 'CC BY 4.0',
   'license_url': 'https://creativecommons.org/licenses/by/4.0/',
   'csv_sha256': hashlib.sha256(Path(CSV).read_bytes()).hexdigest(),
   'original_records': len(rows),
 },
 'models': models,
 'families': families,
 'linked_discoveries': sorted(linked),
}
serialized = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False)
temporary = None
try:
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=Path(OUT).parent, delete=False) as target:
        temporary = Path(target.name)
        target.write(serialized)
    os.replace(temporary, OUT)
finally:
    if temporary is not None:
        temporary.unlink(missing_ok=True)
print('models:', len(models))
print('families:', len(families))
print('linked discoveries:', len(linked), 'of', len(discoveries))
print('families with discoveries and no Epoch model:', [f['name'] for f in families if f['discovery_count'] and not f['model_count']])
print('top:', [(f['name'], f['discovery_count'], f['model_count']) for f in families[:15]])
