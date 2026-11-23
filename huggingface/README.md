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
    path: vulnerabilities.csv
---

# AI Science Tracker

A sourced catalog of scientific discoveries enabled by AI since 2020, plus a separate catalog of software vulnerabilities found with AI.

- **Website:** https://aisciencetracker.org/
- **Methodology:** https://aisciencetracker.org/methodology.html
- **Source code and full data:** https://github.com/marcello-pichini/ai-science-tracker
- **DOI (Zenodo, latest version):** https://doi.org/10.5281/zenodo.24217686

## Contents

| Config | File | Records | Description |
|---|---|---|---|
| `discoveries` (default) | `discoveries.csv`, `.json` | {discoveries} | Scientific results enabled by AI: title, summary, field, AI technology, organization, original source URL, publication date, verification status, paper link and editorial scores (impact, validation, novelty). |
| `vulnerabilities` | `vulnerabilities.csv`, `.json` | {vulnerabilities} | Vulnerabilities attributed to AI systems: product, AI system, disclosure date, CVEs, advisory and source links, remediation status. Kept separate; it does not alter discovery counts. |

Snapshot of the public catalog on {date}. The website and GitHub repository are updated continuously; check them for the current version.

## How records are selected

Each record links an original source (usually the announcing organization's page or the paper) and a date. The catalog lists announcements: most sources are first-party, and an inclusion is not an independent replication. Editorial scores are the maintainer's judgment, described on the methodology page. Cite the original sources for scientific claims.

## Usage

```python
from datasets import load_dataset
discoveries = load_dataset("marcello-pichini/ai-science-tracker", "discoveries", split="train")
```

## License and citation

Catalog content: CC BY 4.0. Attribute as "AI Science Tracker, https://aisciencetracker.org/". Linked sources keep their own terms.

```bibtex
@dataset{pichini_ai_science_tracker,
  author = {Pichini, Marcello},
  title  = {AI Science Tracker},
  doi    = {10.5281/zenodo.24217686},
  url    = {https://aisciencetracker.org/}
}
```
