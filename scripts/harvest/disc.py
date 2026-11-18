"""Discovery adapters: OpenAlex, arXiv, bioRxiv, Europe PMC. Each yields leads for one date window.

Leads are {key, ids, source, date, title, evidence (abstract start), signal (score)}. The score is a cheap
loose prefilter (AI term / validation term / discovery wording / review penalty); precision comes from the
model triage stage. Candidate text is untrusted data.
"""
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

from . import fetch
from .known import norm_doi
from . import blog_sources

AI = re.compile(r"machine[- ]learning|deep[- ]learning|neural network|large language model|\bLLMs?\b|generative|AlphaFold|"
                r"active learning|random forest|graph neural|transformer|reinforcement learning|foundation model|"
                r"language model|diffusion model|\bAI\b|artificial intelligence|Bayesian optimi[sz]ation|surrogate model", re.I)
VALID = re.compile(r"experimentally (validated|confirmed|tested|verified)|experimental validation|in vitro|wet[- ]lab|"
                   r"synthesi[sz]ed|prospective(ly)?|confirmed (in|by)|validated (in|by)|in vivo|crystal structure|cryo-?EM|"
                   r"proof|theorem|conjecture|observed|measured", re.I)
DISC = re.compile(r"\b(discover(ed|y|ies)?|identif(ied|ication)|novel|de novo|designed|prioriti[sz]ed|hits?|new)\b", re.I)
REVIEW = re.compile(r"\b(review|perspective|survey|overview|opportunities|challenges|tutorial|roadmap)\b", re.I)
OA_TERMS = ['"machine learning"', '"deep learning"', '"neural network"', '"generative model"', '"language model"',
            'AlphaFold', '"reinforcement learning"', '"active learning"', '"diffusion model"']
OA_TAIL = '(discovered OR "experimentally validated" OR "in vitro")'   # OpenAlex rejects queries with more than 5 operators
OPENALEX_Q = ('("machine learning" OR "deep learning" OR "neural network" OR "generative model" OR "large language model" OR '
              'AlphaFold OR "active learning" OR "language model" OR "diffusion model" OR "reinforcement learning") AND '
              '(discovered OR discovery OR "de novo" OR "experimentally validated" OR "in vitro" OR synthesized OR prospective OR designed)')
ARXIV_Q = '(abs:"machine learning" OR abs:"deep learning" OR abs:"neural network" OR abs:"language model" OR abs:"reinforcement learning") AND (abs:discovered OR abs:discovery OR abs:"de novo" OR abs:"we find" OR abs:validated)'
ARXIV_CATS = "cat:physics.* OR cat:astro-ph.* OR cat:math.* OR cat:cond-mat.* OR cat:q-bio.* OR cat:stat.ML OR cat:cs.LG OR cat:cs.AI"


def score(title, abstract):
    """Loose prefilter: needs an AI term; validation and discovery wording raise the score, review wording lowers it."""
    text = f"{title} {abstract}"
    if not AI.search(text):
        return 0
    s = (2 if AI.search(title or "") else 1) + (2 if VALID.search(text) else 0)
    s += (1 if DISC.search(title or "") else 0) + (1 if DISC.search(abstract or "") else 0)
    return max(0, s - (3 if REVIEW.search(title or "") else 0))


def lead(source, key, ids, date, title, abstract, sc):
    return {"key": key, "ids": [i for i in ids if i], "source": source, "date": (date or "")[:10], "title": (title or "")[:200],
            "evidence": re.sub(r"\s+", " ", abstract or "")[:400], "signal": sc}


def abstract_from_inverted(inv):
    if not inv:
        return ""
    words = [(pos, w) for w, ps in inv.items() for pos in ps]
    return " ".join(w for _, w in sorted(words))


def openalex(start, end, min_score=0, max_pages=None, report=None, checkpoint=None, budget=None):
    report = report if report is not None else {}
    progress = report.setdefault("cursor", {"term": 0, "page": 1})
    used = 0
    seen = set()
    select = "id,doi,title,publication_date,abstract_inverted_index"
    for ti in range(progress["term"], len(OA_TERMS)):
        term = OA_TERMS[ti]
        n = progress["page"] - 1 if ti == progress["term"] else 0
        while True:   # basic paging (cursor paging needs an API key); max 10,000 results per query
            if (budget or max_pages) and used >= (budget or max_pages):
                report["status"] = "incomplete"
                return
            if n >= 100:
                raise RuntimeError("OpenAlex basic pagination limit reached; split date window before retry")
            q = {"search": f"{term} AND {OA_TAIL}",
                 "filter": f"from_publication_date:{start},to_publication_date:{end},has_abstract:true,type:article|preprint",
                 "per-page": "100", "page": str(n + 1), "select": select}
            d = fetch.get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(q))
            for w in d["results"]:
                if w["id"] in seen:
                    continue
                seen.add(w["id"])
                ab = abstract_from_inverted(w.get("abstract_inverted_index"))
                sc = score(w.get("title") or "", ab)
                if sc >= min_score:
                    doi = norm_doi((w.get("doi") or "").replace("https://doi.org/", ""))
                    yield lead("openalex", doi or w["id"], [doi], w.get("publication_date"), w.get("title"), ab, sc)
            n += 1
            used += 1
            exhausted = len(d["results"]) < 100
            report["cursor"] = {"term": ti + 1, "page": 1} if exhausted else {"term": ti, "page": n + 1}
            progress = report["cursor"]
            if checkpoint:
                checkpoint()
            if exhausted:
                break
    report["status"] = "complete"


def arxiv(start, end, min_score=0, max_results=None, report=None, checkpoint=None, budget=None):
    report = report if report is not None else {}
    used = 0
    s, e = start.replace("-", ""), end.replace("-", "")
    q = f"({ARXIV_Q}) AND ({ARXIV_CATS}) AND submittedDate:[{s}0000 TO {e}2359]"
    got, ns = report.get("cursor", 0), {"a": "http://www.w3.org/2005/Atom"}
    while True:
        if (budget and used >= budget) or (max_results and used * 200 >= max_results):
            report["status"] = "incomplete"
            return
        url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": q, "start": got, "max_results": 200})
        root = ET.fromstring(fetch.get_text(url.replace("http://", "https://"), max_bytes=50 * 1024 ** 2))
        entries = root.findall("a:entry", ns)
        if any("/api/errors" in en.findtext("a:id", "", ns) for en in entries):
            raise RuntimeError("arXiv returned an API error entry")
        for en in entries:
            title = " ".join((en.findtext("a:title", "", ns) or "").split())
            ab = " ".join((en.findtext("a:summary", "", ns) or "").split())
            sc = score(title, ab)
            aid = (en.findtext("a:id", "", ns) or "").rsplit("/abs/", 1)[-1].split("v")[0]
            if sc >= min_score:
                yield lead("arxiv", f"arXiv:{aid}", [f"arXiv:{aid}"], en.findtext("a:published", "", ns), title, ab, sc)
        got += len(entries)
        used += 1
        report["cursor"] = got
        if checkpoint:
            checkpoint()
        time.sleep(3)  # arXiv asks for one request per 3 seconds
        if len(entries) < 200:
            report["status"] = "complete"
            break


def biorxiv(start, end, min_score=0, server="biorxiv", report=None, checkpoint=None, budget=None):
    report = report if report is not None else {}
    cursor = report.get("cursor", 0)
    used = 0
    while True:
        if budget and used >= budget:
            report["status"] = "incomplete"
            return
        d = fetch.get_json(f"https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}")
        rows = d.get("collection", [])
        for r in rows:
            sc = score(r.get("title", ""), r.get("abstract", ""))
            if sc >= min_score:
                doi = norm_doi(r.get("doi"))
                yield lead(server, doi, [doi], r.get("date"), r.get("title"), r.get("abstract"), sc)
        total = int(d["messages"][0]["total"])
        if not rows and cursor < total:
            raise RuntimeError("bioRxiv returned an empty page before total exhaustion")
        cursor += len(rows)
        used += 1
        report["cursor"] = cursor
        if checkpoint:
            checkpoint()
        if cursor >= total:
            report["status"] = "complete"
            break


def europepmc(start, end, min_score=0, pages=None, report=None, checkpoint=None, budget=None):
    report = report if report is not None else {}
    used = 0
    q = f"({OPENALEX_Q}) AND FIRST_PDATE:[{start} TO {end}] AND NOT PUB_TYPE:\"review\""
    params = {"query": q, "format": "json", "resultType": "core", "pageSize": "100", "cursorMark": "*", "sort": "FIRST_PDATE_D desc"}
    params["cursorMark"] = report.get("cursor", "*")
    while True:
        if (budget or pages) and used >= (budget or pages):
            report["status"] = "incomplete"
            return
        d = fetch.get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params))
        res = d["resultList"]["result"]
        for r in res:
            sc = score(r.get("title", ""), r.get("abstractText", ""))
            if sc >= min_score:
                doi = norm_doi(r.get("doi"))
                yield lead("europepmc", doi or r.get("id"), [doi], r.get("firstPublicationDate"), r.get("title"), r.get("abstractText"), sc)
        nxt = d.get("nextCursorMark")
        if not res or (d.get("hitCount") is not None and int(d["hitCount"]) <= used * 100 + len(res)):
            report["status"] = "complete"
            break
        if not nxt or nxt == params["cursorMark"]:
            raise RuntimeError("Europe PMC cursor stalled before proven exhaustion")
        params["cursorMark"] = nxt
        report["cursor"] = nxt
        used += 1
        if checkpoint:
            checkpoint()


ADAPTERS = {"openalex": openalex, "arxiv": arxiv, "biorxiv": biorxiv, "europepmc": europepmc}


# ---- lab feeds and sitemaps -------------------------------------------------------------------------------------
LAB_FEEDS = {
    "deepmind": "https://deepmind.google/blog/rss.xml",
    "google-research": "https://research.google/blog/rss/",
    "openai": "https://openai.com/news/rss.xml",
    "nature-ml": "https://www.nature.com/subjects/machine-learning.rss",
    "nvidia": "https://blogs.nvidia.com/feed/",
}
LAB_SITEMAPS = {"deepmind": "https://deepmind.google/sitemap.xml", "anthropic": "https://www.anthropic.com/sitemap.xml"}
SCIENCE = re.compile(r"discover|scientist|protein|enzyme|antibod|antibiotic|drug|molecul|genom|DNA|RNA|cell|disease|cancer|"
                     r"materials?|crystal|chemist|physic|quantum|math|proof|theorem|conjecture|climate|weather|forecast|"
                     r"astronom|galax|biolog|medicine|clinical|fusion|battery|catalys|AlphaFold|AlphaProof|AlphaEvolve|"
                     r"GNoME|\bAI for science\b|co-scientist|research", re.I)
NS = {"a": "http://www.w3.org/2005/Atom", "c": "http://purl.org/rss/1.0/modules/content/"}


def feed_items(xml_text):
    yield from blog_sources.feed_items(xml_text)


def sitemap_urls(xml_text):
    root = ET.fromstring(xml_text)
    for u in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
        loc = u.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc", "")
        yield loc, (u.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod", "") or "")[:10]


def slug_title(url):
    return re.sub(r"[-_]+", " ", url.rstrip("/").rsplit("/", 1)[-1]).strip()


def labs(min_score=1):
    """Posts from lab feeds and sitemaps that look scientific; every item is a lead, the triage decides."""
    for name, url in LAB_FEEDS.items():
        try:
            items = list(feed_items(fetch.get_text(url, max_bytes=20 * 1024 ** 2)))
        except Exception as e:
            print(f"  feed {name}: {str(e)[:60]}")
            continue
        for title, link, date, desc in items:
            text = re.sub(r"<[^>]+>", " ", f"{title} {desc}")
            sc = len(set(m.lower() for m in SCIENCE.findall(text)))
            if sc >= min_score and link:
                yield lead(f"lab:{name}", link, [link], date, title, text, min(sc, 9))
    for name, url in LAB_SITEMAPS.items():
        try:
            urls = list(sitemap_urls(fetch.get_text(url, max_bytes=50 * 1024 ** 2)))
        except Exception as e:
            print(f"  sitemap {name}: {str(e)[:60]}")
            continue
        for loc, date in urls:
            if "/blog/" in loc or "/news/" in loc or "/research/" in loc:
                t = slug_title(loc)
                sc = len(set(m.lower() for m in SCIENCE.findall(t)))
                if sc >= min_score:
                    yield lead(f"lab-sitemap:{name}", loc, [loc], date, t, "", min(sc, 9))
    for name in blog_sources.SOURCES:
        yield from research_blog(name)


def research_blog(name, start=None, end=None, report=None):
    report = report if report is not None else {}
    for title, url, date, text in blog_sources.source_items(name, report=report):
        if date and ((start and date < start) or (end and date > end)):
            continue
        row = lead(f"research-blog:{name}", url, [url], date, title, text, max(1, score(title, text)))
        row['listing_url'] = blog_sources.SOURCES[name]['url']
        row['date_basis'] = 'source listing' if date else 'date not extracted from listing; verify original article'
        yield row
    print(f"  {name}: {report.get('status')} — {report.get('items', 0)} listing entries; "
          f"{report.get('unknown_dates', 0)} dates require article verification; "
          f"{report.get('coverage') or report.get('error') or 'exposed listing pages only'}", file=sys.stderr)


ADAPTERS["labs"] = lambda start, end, min_score=1: (ld for ld in labs(min_score) if start <= (ld["date"] or "9999") <= end or not ld["date"])
for _source_name in blog_sources.SOURCES:
    ADAPTERS[_source_name] = lambda start, end, min_score=1, name=_source_name: research_blog(name, start, end)
