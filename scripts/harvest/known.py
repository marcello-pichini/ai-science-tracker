"""Dedupe index of what the catalog already holds (active, archived, optional extra ledgers)."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
ID_RE = re.compile(r"CVE-\d{4}-\d{4,}|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}", re.I)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#,;)\]]+")
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})|arXiv:(\d{4}\.\d{4,5})", re.I)


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def norm_url(u):
    return (u or "").lower().split("#")[0].rstrip("/")


def norm_doi(d):
    return (d or "").lower().rstrip(".")


class Known:
    def __init__(self, root=ROOT):
        root = Path(root)
        text = lambda p: (root / p).read_text(encoding="utf-8") if (root / p).exists() else "[]"
        self.ids = set()
        for record in json.loads(text("data/vulnerabilities.json")):
            identities = [record.get("id", ""), *record.get("cves", [])]
            identities += [urlsplit(record.get(key, "")).path
                           for key in ("source_url", "ai_source_url", "advisory_url")]
            self.ids.update(m.upper() for value in identities for m in ID_RE.findall(value))
        self.excluded_vulnerabilities = {
            r["case_key"].upper() for r in json.loads(text("research/vulnerability-exclusions.json"))
        }
        self.dois, self.urls, self.titles, self.arxiv = set(), set(), set(), set()
        for name in ("data/discoveries.json", "data/archived-discoveries.json"):
            for r in json.loads(text(name)):
                primary_urls = [r.get(key) or "" for key in ("source_url", "paper_url")]
                self.urls |= {norm_url(url) for url in primary_urls}
                self.titles.add(norm_title(r.get("title")))
                self.dois |= {norm_doi(d) for url in primary_urls for d in DOI_RE.findall(url)}
                self.arxiv |= {a or b for url in primary_urls for a, b in ARXIV_RE.findall(url)}
        self.urls.discard("")
        self.excluded = {norm_doi(r["case_key"]) for r in json.loads(text("research/discovery-exclusions.json"))}

    def vuln(self, *ids):
        return any(token.upper() in self.ids or token.upper() in self.excluded_vulnerabilities
                   for ident in ids for token in (ident, *ID_RE.findall(ident)))

    def paper(self, doi=None, url=None, title=None, arxiv=None, key=None):
        return bool(norm_doi(key) in self.excluded or norm_doi(doi) in self.excluded
                    or (doi and norm_doi(doi) in self.dois) or (url and norm_url(url) in self.urls)
                    or (title and norm_title(title) in self.titles) or (arxiv and arxiv in self.arxiv))
