"""Vulnerability adapters: each yields leads {key, ids, source, date, title, evidence, signal}.

Strong signal = a vendor/researcher in the credits, an AI-flagged bug, or a lab index listing.
Weak signal = AI wording in a description only. Leads are not admissions.
"""
import concurrent.futures as cf
import json
import re
import zipfile
from pathlib import Path

from . import fetch
from .known import ID_RE, Known

CREDIT_RE = re.compile(
    r"\bAISLE\b|\bAnthropic\b|\bClaude\b|Mythos|\bOpenAI\b|\bCodex\b|GPT-?5|Aardvark|Big ?Sleep|DeepMind|CodeMender|"
    r"Project Zero|GitHub Security Lab|Taskflow|MDASH|\bFORGE\b|\bMORSE\b|\bXBOW\b|\bXint\b|Revelio|Endor Labs|"
    r"Trail of Bits|Buttercup|Carlini|Joshua Rogers|Stanislav Fort|Camastra|kylebot|Korczynski|Ada Logics", re.I)
DESC_RE = re.compile(r"(found|discovered|identified|reported)( \w+){0,3} (by|using|with) (an? )?(AI|LLM|AI agent)\b|"
                     r"\bAI[- ](assisted|discovered|found|generated)", re.I)
OSV_ECOSYSTEMS = ["GIT", "Linux", "Go", "PyPI", "npm", "Maven", "crates.io", "RubyGems", "Packagist", "NuGet", "Hex",
                  "OSS-Fuzz", "GitHub Actions", "Debian"]
LAB_INDEXES = {"anthropic-cvd": "https://red.anthropic.com/2026/cvd/", "aisle": "https://aisle.com/cve-discoveries/"}
CVE_RAW = "https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves"


def classify(credits, desc=""):
    if CREDIT_RE.search(credits or ""):
        return "credit"
    return "desc" if DESC_RE.search(desc or "") else None


def lead(source, ids, date, title, evidence, signal):
    ids = sorted({i.upper() for i in ids if i})
    return {"key": ids[0] if ids else f"{source}:{title[:40]}", "ids": ids, "source": source, "date": (date or "")[:10],
            "title": (title or "")[:160], "evidence": (evidence or "")[:300].replace("\n", " "), "signal": signal}


def cve_url(cve_id):
    _, year, num = cve_id.split("-")
    return f"{CVE_RAW}/{year}/{int(num) // 1000}xxx/{cve_id}.json"


def from_cve_record(rec, source="cvelist"):
    cna = rec.get("containers", {}).get("cna", {})
    credits = "; ".join(c.get("value", "") for c in cna.get("credits", []))
    desc = " ".join(d.get("value", "") for d in cna.get("descriptions", []))
    sig = classify(credits, desc)
    if not sig:
        return None
    meta = rec.get("cveMetadata", {})
    return lead(source, [meta.get("cveId")] + [a for a in cna.get("aliases", [])], meta.get("datePublished"),
                cna.get("title") or desc, credits or desc, sig)


def cvelist_ids(cve_ids, workers=8):
    """Leads for specific CVEs (used by backtests and re-checks)."""
    def one(i):
        try:
            return from_cve_record(fetch.get_json(cve_url(i)))
        except Exception:
            return None
    with cf.ThreadPoolExecutor(workers) as ex:
        return [x for x in ex.map(one, cve_ids) if x]


def cvelist_delta(days=1, known=None, workers=8):
    """New CVEs in the cvelistV5 delta log of the last `days`."""
    import datetime as dt
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    log = fetch.get_json(f"{CVE_RAW}/deltaLog.json", max_bytes=200 * 1024 ** 2)
    ids = sorted({i["cveId"] for e in log if e["fetchTime"].replace("Z", "")[:19] > since for i in e.get("new", [])})
    if known:
        ids = [i for i in ids if not known.vuln(i)]
    return cvelist_ids(ids, workers)


def cvelist_archive(zip_path, from_year=2024, known=None):
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            p = name.split("/")
            if not name.endswith(".json") or len(p) < 4 or not p[-1].startswith("CVE-") or not p[-3].isdigit() or int(p[-3]) < from_year:
                continue
            if known and known.vuln(p[-1][:-5]):
                continue
            ld = from_cve_record(json.loads(z.read(name)), "cvelist-archive")
            if ld:
                out.append(ld)
    return out


def osv_entry(e):
    credits = "; ".join(c.get("name", "") for c in e.get("credits", []) or [])
    text = f"{e.get('summary', '')} {e.get('details', '')}"
    sig = classify(credits, text)
    if not sig:
        return None
    return lead("osv", [e.get("id")] + (e.get("aliases") or []), e.get("published"), e.get("summary") or e.get("id"),
                credits or text, sig)


def osv(ecosystems=OSV_ECOSYSTEMS, known=None):
    """Download each ecosystem zip (data only), scan entries, return leads. Raw files are deleted by the caller."""
    out = []
    for eco in ecosystems:
        path = fetch.download(f"https://osv-vulnerabilities.storage.googleapis.com/{eco.replace(' ', '%20')}/all.zip", f"osv-{eco}")
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.endswith(".json"):
                    continue
                ld = osv_entry(json.loads(z.read(name)))
                if ld and not (known and known.vuln(*ld["ids"])):
                    out.append(ld)
    return out


def lab_index(name, known=None):
    """CVE ids listed on a lab's own discovery index; all strong signals (the lab claims the finding)."""
    text = fetch.get_text(LAB_INDEXES[name], max_bytes=20 * 1024 ** 2)
    ids = sorted({m.upper() for m in ID_RE.findall(text) if m.upper().startswith("CVE-")})
    return [lead(f"lab:{name}", [i], "", i, f"listed on {LAB_INDEXES[name]}", "index") for i in ids
            if not (known and known.vuln(i))]


def mozilla(known=None):
    """Compatibility list wrapper around the streaming advisory scan."""
    return list(iter_mozilla(known))


def iter_mozilla(known=None):
    """CVEs of Mozilla advisories that cite a bug carrying the ai-involved keyword."""
    ai_bugs, offset = set(), 0
    while True:
        d = fetch.get_json("https://bugzilla.mozilla.org/rest/bug?keywords=ai-involved&include_fields=id&limit=500&offset=%d" % offset)
        ids = [b["id"] for b in d["bugs"]]
        ai_bugs |= set(ids)
        if len(ids) < 500:
            break
        offset += 500
    path = fetch.download("https://github.com/mozilla/foundation-security-advisories/archive/refs/heads/master.zip", "mfsa", "mfsa.zip")
    out = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith((".yml", ".yaml")):
                continue
            body = z.read(name).decode("utf-8", "replace")
            # per-CVE blocks: "  CVE-...:" followed by lines (reporter, bugs: - url: 123456)
            for m in re.finditer(r"^  (CVE-\d{4}-\d{4,}):\n((?:    .*\n?)*)", body, re.M):
                bugs = {int(x) for x in re.findall(r"url:\s*(?:https?://\S*id=)?(\d{5,8})\b", m.group(2))}
                hit = bugs & ai_bugs
                if hit and not (known and known.vuln(m.group(1))):
                    yield lead("mozilla", [m.group(1)], "", f"Mozilla advisory {Path(name).stem}",
                               "bug %s flagged ai-involved" % sorted(hit)[0], "ai-bug")
