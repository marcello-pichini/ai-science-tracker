"""Generate data/models.json from Epoch AI CSV and data/discoveries.json.

Source: Epoch AI, Data on AI models, CC BY 4.0.
Place the downloaded CSV at work/epoch/notable_ai_models.csv, then run from
this repository root: python3 scripts/generate_models.py
"""
import csv, json, re, datetime

CSV = 'work/epoch/notable_ai_models.csv'
DISCOVERIES = 'data/discoveries.json'
OUT = 'data/models.json'

LAB = re.compile(r'^(openai|google deepmind|deepmind|google|google research|google brain|google cloud|google ai|anthropic|microsoft|microsoft research|microsoft research asia|meta ai|meta|facebook ai research|nvidia|baidu|alibaba|bytedance|deepseek|tencent|huawei|mistral ai|xai|ibm|amazon|z\.ai|moonshot|minimax|evolutionaryscale|apple|cohere)', re.I)

# Model families: ID, display name, Epoch model regex, discovery technology regex.
FAMILIES = [
 ('alphafold','AlphaFold', r'^alphafold($| 2|-multimer)', r'alphafold(?! 3)'),
 ('alphafold3','AlphaFold 3', r'^alphafold 3', r'alphafold 3'),
 ('alphagenome','AlphaGenome', r'alphagenome', r'alphagenome'),
 ('alphamissense','AlphaMissense', r'alphamissense', r'alphamissense'),
 ('alphaproteo','AlphaProteo', r'alphaproteo', r'alphaproteo'),
 ('alphaevolve','AlphaEvolve', r'alphaevolve', r'alphaevolve'),
 ('alphadev','AlphaDev', r'alphadev', r'alphadev'),
 ('alphageometry','AlphaGeometry', r'alphageometry', r'alphageometry'),
 ('alphatensor','AlphaTensor', r'alphatensor', r'alphatensor'),
 ('alphaqubit','AlphaQubit', r'alphaqubit', r'alphaqubit'),
 ('alphaproof','AlphaProof', r'alphaproof', r'alphaproof'),
 ('alphacode','AlphaCode', r'alphacode', r'alphacode'),
 ('funsearch','FunSearch', r'funsearch', r'funsearch'),
 ('gnome','GNoME', r'gnome', r'gnome'),
 ('graphcast','GraphCast', r'graphcast', r'graphcast'),
 ('gencast','GenCast', r'gencast', r'gencast'),
 ('weathernext','WeatherNext', r'weathernext', r'weathernext'),
 ('neuralgcm','NeuralGCM', r'neuralgcm', r'neuralgcm'),
 ('metnet','MetNet', r'^metnet', r'metnet'),
 ('fourcastnet','FourCastNet', r'fourcastnet', r'fourcastnet'),
 ('pangu','Pangu-Weather', r'pangu-weather', r'pangu'),
 ('corrdiff','CorrDiff', r'corrdiff', r'corrdiff'),
 ('fastnet','FastNet', r'^fastnet', r'fastnet'),
 ('aifs','AIFS (ECMWF)', r'^aifs', r'aifs'),
 ('mattergen','MatterGen', r'mattergen', r'mattergen'),
 ('mattersim','MatterSim', r'mattersim', r'mattersim'),
 ('coscientist','AI Co-Scientist', r'co-scientist', r'co-scientist'),
 ('gemini','Gemini', r'^gemini', r'gemini'),
 ('gpt4','GPT-4', r'^gpt-4', r'gpt-4(?!b)'),
 ('gpt5','GPT-5', r'^gpt-5', r'gpt-5'),
 ('gpt6','GPT-6', r'^gpt-6', r'gpt-6'),
 ('oserie','o1 / o3', r'^(o1|o3)\b', r'\bo1\b|\bo3\b'),
 ('codex','Codex', r'^codex|codex', r'codex'),
 ('claude','Claude', r'^claude', r'claude'),
 ('esm','ESM / ESMFold', r'^esm', r'\besm'),
 ('evo','Evo', r'^evo\b', r'\bevo\b|evo 2'),
 ('rfdiffusion','RFdiffusion', r'rfdiffusion', r'rfdiffusion'),
 ('proteinmpnn','ProteinMPNN', r'proteinmpnn', r'proteinmpnn'),
 ('rosettafold','RoseTTAFold', r'rosettafold', r'rosettafold'),
 ('trrosetta','trRosetta', r'trrosetta', r'trrosetta'),
 ('genslm','GenSLM', r'genslm', r'genslm'),
 ('lineardesign','LinearDesign', r'lineardesign', r'lineardesign'),
 ('retrochimera','RetroChimera', r'retrochimera', r'retrochimera'),
 ('boltz','Boltz', r'^boltz', r'boltz'),
 ('chroma','Chroma', r'^chroma', r'chroma'),
 ('enformer','Enformer', r'enformer', r'enformer'),
 ('deepconsensus','DeepConsensus', r'deepconsensus', r'deepconsensus'),
 ('medpalm','Med-PaLM', r'med-palm', r'med-palm'),
 ('txgemma','TxGemma', r'txgemma', r'txgemma'),
 ('dolphingemma','DolphinGemma', r'dolphingemma', r'dolphingemma'),
 ('aurora','Aurora', r'^aurora', r'\baurora\b'),
 ('skala','Skala', r'^skala', r'\bskala\b'),
 ('perch','Perch', r'^perch', r'\bperch\b'),
 ('synthidbio','SynthID Bio', r'synthid', r'synthid'),
 ('nucleotide','Nucleotide Transformer', r'nucleotide transformer', r'nucleotide transformer'),
 ('progen','ProGen', r'^progen', r'progen'),
 ('opencrispr','OpenCRISPR', r'opencrispr', r'opencrispr'),
 ('kosmos','Kosmos', r'^kosmos', r'\bkosmos\b'),
 ('grok','Grok', r'^grok', r'\bgrok\b'),
 ('llama','Llama', r'^llama', r'\bllama\b'),
 ('qwen','Qwen', r'^qwen', r'\bqwen\b'),
 ('deepseekm','DeepSeek', r'^deepseek', r'deepseek'),
]

def num(s):
    try: return float(s)
    except: return None

rows = list(csv.DictReader(open(CSV, encoding='utf-8')))
discoveries = json.load(open(DISCOVERIES, encoding='utf-8'))

def text(s):
    return ' '.join([s.get('ai_technology',''), s.get('title','')]).lower()

models = []
for r in rows:
    name = (r.get('Model') or '').strip()
    org  = (r.get('Organization') or '').strip()
    date = (r.get('Publication date') or '').strip()
    if not name or not date:
        continue
    fam = next((f[0] for f in FAMILIES if re.search(f[2], name, re.I)), None)
    recent_lab = date >= '2020-01-01' and LAB.search(org)
    if not (recent_lab or fam):
        continue
    models.append({
        'name': name,
        'organization': org,
        'date': date,
        'domain': (r.get('Domain') or '').strip(),
        'parameters': num(r.get('Parameters','')),
        'compute_flop': (r.get('Training compute (FLOP)') or '').strip(),
        'access': (r.get('Model accessibility') or '').strip(),
        'frontier': (r.get('Frontier model') or '').strip().lower() == 'true',
        'link': (r.get('Link') or '').strip().split(' ')[0],
        'family': fam,
    })
models.sort(key=lambda m: m['date'], reverse=True)

families = []
linked = set()
for fid, name, re_mod, re_sco in FAMILIES:
    sc = [s['id'] for s in discoveries if re.search(re_sco, text(s), re.I)]
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
   'downloaded': '2026-11-12',
   'original_records': len(rows),
 },
 'models': models,
 'families': families,
 'linked_discoveries': sorted(linked),
}
json.dump(out, open(OUT,'w',encoding='utf-8'), ensure_ascii=False, indent=1)
print('models:', len(models))
print('families:', len(families))
print('linked discoveries:', len(linked), 'of', len(discoveries))
print('families with discoveries and no Epoch model:', [f['name'] for f in families if f['discovery_count'] and not f['model_count']])
print('top:', [(f['name'], f['discovery_count'], f['model_count']) for f in families[:15]])
