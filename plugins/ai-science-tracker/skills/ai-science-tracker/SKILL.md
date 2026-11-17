---
name: ai-science-tracker
description: Keep the user up to date on scientific discoveries enabled by AI, AI model releases linked to them, and publicly disclosed vulnerabilities found with AI, using the AI Science Tracker catalog instead of a general web search. Use for "what's new in AI for science", "recent AI discoveries", "which discoveries used AlphaFold/Claude/GPT", "new AI-found CVEs", weekly digests, or looking up a tracker entry by ID.
---

# AI Science Tracker

Answer from the curated catalog at https://aisciencetracker.org/ . Do not run a general web search unless the user asks to go beyond the catalog; if they do, say which results come from outside it.

## How

Run the bundled script (Python 3 standard library, reads the live site):

```bash
python3 scripts/tracker.py new --days 30              # all collections, last 30 days
python3 scripts/tracker.py new --since 2026-11-01 --collection discoveries
python3 scripts/tracker.py search "AlphaFold" --collection discoveries
python3 scripts/tracker.py search "CVE-2025-37899"
python3 scripts/tracker.py get 2020-11-alphafold-casp14   # full record
python3 scripts/tracker.py info                            # counts, data date, endpoints
```

Collections: `discoveries`, `models`, `vulnerabilities`, `all` (default). "New" means: discoveries by catalog `added_date`, vulnerabilities by `checked_date`, models by release `date`.

If Python or shell is unavailable, fetch these instead (do not fetch the multi-megabyte JSON files through a summarizing fetch tool):
- What's new: https://aisciencetracker.org/feed.xml (Atom, latest discovery additions and vulnerability checks)
- One record: `api/v1/discoveries/{id}.json` or `api/v1/vulnerabilities/{id}.json`
- Overview and endpoints: `api/v1/index.json`, `llms.txt`

## Reporting

- Group by collection; for each item give date, title, organization and the tracker link. Use `get` before describing a record in detail.
- Keep the catalog's caveats: figures are reported by the sources and not independently verified; relevance scores are editorial; entry counts are not counts of independent findings. Vulnerability records never count as scientific discoveries.
- For a scientific claim, point to the original source (`source_url`, `paper_url`) in the record, not only the tracker.
- The catalog is manual and not exhaustive: an empty result means "not in the tracker", not "does not exist".
- Attribution: catalog content CC BY 4.0 ("AI Science Tracker"); model data from Epoch AI, CC BY 4.0.
