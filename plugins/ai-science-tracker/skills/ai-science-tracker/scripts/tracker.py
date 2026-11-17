#!/usr/bin/env python3
"""Query the published AI Science Tracker data (standard library only).

  tracker.py new [--since YYYY-MM-DD | --days N] [--collection C] [--limit N]
  tracker.py search TEXT [--collection C] [--limit N]
  tracker.py get ID
  tracker.py info

C is discoveries, models, vulnerabilities or all (default).
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("AI_SCIENCE_TRACKER_BASE",
                      "https://aisciencetracker.org").rstrip("/")
COLLECTIONS = ("discoveries", "models", "vulnerabilities")
# Date that means "new to the reader" per collection, and the fields searched.
DATE_FIELD = {"discoveries": "added_date", "models": "date", "vulnerabilities": "checked_date"}
TEXT_FIELDS = {
    "discoveries": ("id", "title", "summary", "field", "ai_technology", "organization"),
    "models": ("name", "organization", "domain", "family"),
    "vulnerabilities": ("id", "title", "product", "ai_system", "organization", "summary", "cves"),
}


def fetch(path):
    req = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": "ai-science-tracker-skill"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def records(name):
    data = fetch(f"data/{name}.json")
    return data["models"] if name == "models" else data


def link(name, r):
    if name == "discoveries":
        return f"{BASE}/share/{r['id']}.html"
    if name == "vulnerabilities":
        return f"{BASE}/security.html#{urllib.parse.quote(r['id'])}"
    return r.get("link") or f"{BASE}/models.html"


def line(name, r):
    if name == "models":
        return f"[model] {r.get('date', '?')} {r['name']} ({r.get('organization', '?')}) {link(name, r)}"
    when = r.get(DATE_FIELD[name]) or "?"
    org = r.get("organization") or "?"
    tag = "discovery" if name == "discoveries" else "vulnerability"
    return f"[{tag}] {when} {r['title']} ({org}) {link(name, r)}"


def text(r, fields):
    return " ".join(json.dumps(r.get(f, ""), ensure_ascii=False) for f in fields).lower()


def selected(c):
    return COLLECTIONS if c == "all" else (c,)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--since")
    n.add_argument("--days", type=int, default=30)
    s = sub.add_parser("search")
    s.add_argument("text")
    for q in (n, s):
        q.add_argument("--collection", choices=COLLECTIONS + ("all",), default="all")
        q.add_argument("--limit", type=int, default=25)
    sub.add_parser("get").add_argument("id")
    sub.add_parser("info")
    a = p.parse_args(argv)

    if a.cmd == "info":
        print(json.dumps(fetch("api/v1/index.json"), indent=1))
        return 0
    if a.cmd == "get":
        for name in ("discoveries", "vulnerabilities"):
            try:
                print(json.dumps(fetch(f"api/v1/{name}/{urllib.parse.quote(a.id)}.json"), indent=1, ensure_ascii=False))
                return 0
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
        print(f"No discovery or vulnerability with id {a.id!r}", file=sys.stderr)
        return 1

    needle = a.text.lower() if a.cmd == "search" else None
    since = None if needle else a.since or (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
    for name in selected(a.collection):
        rows = records(name)
        if needle is None:
            rows = [r for r in rows if (r.get(DATE_FIELD[name]) or "") >= since]
        else:
            rows = [r for r in rows if needle in text(r, TEXT_FIELDS[name])]
        rows.sort(key=lambda r: r.get(DATE_FIELD[name]) or "", reverse=True)
        scope = f"since {since}" if needle is None else f"matching {a.text!r}"
        print(f"## {name}: {len(rows)} {scope}" + (f" (showing {a.limit})" if len(rows) > a.limit else ""))
        for r in rows[:a.limit]:
            print(line(name, r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
