"""Dedupe index of what the catalog already holds (active, archived, optional extra ledgers)."""
import json
import re
from pathlib import Path

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
        vuln = text("data/vulnerabilities.json")
        self.ids = {m.upper() for m in ID_RE.findall(vuln)}
        self.excluded_vulnerabilities = {
            r["case_key"].upper() for r in json.loads(text("research/vulnerability-exclusions.json"))
        }
        self.dois, self.urls, self.titles, self.arxiv = set(), set(), set(), set()
        for name in ("data/discoveries.json", "data/archived-discoveries.json"):
            blob = text(name)
            for r in json.loads(blob):
                self.urls |= {norm_url(r.get("source_url")), norm_url(r.get("paper_url"))}
                self.titles.add(norm_title(r.get("title")))
            self.dois |= {norm_doi(d) for d in DOI_RE.findall(blob)}
            self.arxiv |= {a or b for a, b in ARXIV_RE.findall(blob)}
        self.urls.discard("")
        self.excluded = {norm_doi(r["case_key"]) for r in json.loads(text("research/discovery-exclusions.json"))}

    def vuln(self, *ids):
        return any(i.upper() in self.ids or i.upper() in self.excluded_vulnerabilities for i in ids)

    def paper(self, doi=None, url=None, title=None, arxiv=None, key=None):
        return bool(norm_doi(key) in self.excluded or norm_doi(doi) in self.excluded
                    or (doi and norm_doi(doi) in self.dois) or (url and norm_url(url) in self.urls)
                    or (title and norm_title(title) in self.titles) or (arxiv and arxiv in self.arxiv))
