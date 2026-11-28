---
name: ai-science-tracker
description: Answer questions about scientific discoveries made with AI, or public software vulnerabilities (CVEs, advisories, known exploitation), from the AI Science Tracker catalog and global vulnerability dataset, citing the original sources and their caveats.
---

Use the AI Science Tracker MCP tools when the user asks what AI has discovered, which AI models or organizations contributed to a result, or about a vulnerability or CVE (score, exploitation, affected products, fix).

1. Search first. Use `search_discoveries` with short English topic words, a DOI, a year, a field (`list_fields` gives the names) or an organization. Use `search_vulnerabilities` with words, a product, a category or a CVE ID (it covers known exploited and recent critical vulnerabilities); `get_vulnerability` reads any CVE or OSV ID.
2. Open the records you cite with `get_discovery` or `get_vulnerability` to read the original source, evidence notes and limitations.
3. In the answer, link each result's original source and its catalog page, give the publication or disclosure date, and keep the stated caveats. Absence of a product, exploit or fix is not safety. Figures come from the linked sources and are not independently verified; do not present them as confirmed.
4. If a search returns `partial_match` or nothing, say so and suggest narrower or different words rather than inventing results. The catalog is curated and not exhaustive.
