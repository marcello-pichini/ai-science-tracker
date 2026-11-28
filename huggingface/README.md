---
pretty_name: AI Science Tracker
license: cc-by-4.0
language:
- en
size_categories:
- {size}
task_categories:
- text-classification
- tabular-classification
tags:
- ai-for-science
- scientific-discovery
- science
- catalog
- security
- vulnerabilities
- tabular
configs:
- config_name: discoveries
  default: true
  data_files:
  - split: train
    path: discoveries.csv
- config_name: vulnerabilities
  data_files:
  - split: train
    path: vulnerabilities/vulnerabilities_global.jsonl.gz
---

# AI Science Tracker

A sourced catalog of scientific discoveries enabled by AI since 2020, plus the global vulnerability dataset: the largest and most complete vulnerability dataset in the world, with {vulnerabilities} vulnerabilities joined from {vulnerability_sources} public sources into one record each.

- **Website:** https://aisciencetracker.org/
- **Methodology:** https://aisciencetracker.org/methodology.html
- **Source code and full data:** https://github.com/marcello-pichini/ai-science-tracker
- **DOI (Zenodo, latest version):** https://doi.org/10.5281/zenodo.24217686

## Contents

| Config | File | Records | Description |
|---|---|---|---|
| `discoveries` (default) | `discoveries.csv`, `.json` | {discoveries} | Scientific results enabled by AI: title, summary, field, AI technology, organization, original source URL, publication date, verification status, paper link and editorial scores (impact, validation, novelty). |
| `vulnerabilities` | `vulnerabilities/vulnerabilities_global.jsonl.gz` | {vulnerabilities} | Every public CVE (published and rejected) and every advisory without a CVE from allowlisted OSV sources, GCVE and national databases, one record each: scores from every scorer, affected products and version ranges, fixes and fixing commits, CWE, CAPEC and ATT&CK, public exploits, CISA KEV, ENISA EUVD, EPSS, sightings and links to every advisory. Built {vulnerability_built}. Field reference: https://github.com/marcello-pichini/ai-science-tracker/blob/main/docs/vulnerability-global-schema.md |

The `vulnerabilities/` folder also holds the aggregates: `products.json.gz`, `vendors.json.gz`, `weaknesses.json.gz`, `categories.json.gz`, `product_lifecycle.json.gz`, `product_versions.jsonl.gz` (one line per product and vulnerability with version ranges) and `malicious_packages.jsonl.gz` (OpenSSF malicious packages, kept apart), plus `build_report.json`.

Snapshot of the public catalog on {date}. The website and GitHub repository are updated continuously; check them for the current version.

## How records are selected

Each record links an original source (usually the announcing organization's page or the paper) and a date. The catalog lists announcements: most sources are first-party, and an inclusion is not an independent replication. Editorial scores are the maintainer's judgment, described on the methodology page. Cite the original sources for scientific claims.

## Usage

```python
from datasets import load_dataset
discoveries = load_dataset("marcello-pichini/ai-science-tracker", "discoveries", split="train")
vulnerabilities = load_dataset("marcello-pichini/ai-science-tracker", "vulnerabilities", split="train")
```

## Global vulnerability dataset: sources and terms

Each field keeps its source; scores are never merged. Absence of a product, exploit or fix in a record does not mean the product is unaffected, unexploited or unpatched. Counts reflect disclosure and research attention, not product safety. Sources that publish no reuse terms contribute identifiers and links only.

| Source | Terms | Notice |
|---|---|---|
{vulnerability_source_table}

## License and citation

Catalog content and the vulnerability dataset's derived fields: CC BY 4.0. Attribute as "AI Science Tracker, https://aisciencetracker.org/". Linked and joined sources keep their own terms (table above).

```bibtex
@dataset{pichini_ai_science_tracker,
  author = {Pichini, Marcello},
  title  = {AI Science Tracker},
  doi    = {10.5281/zenodo.24217686},
  url    = {https://aisciencetracker.org/}
}
```
