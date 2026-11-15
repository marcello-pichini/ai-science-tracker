# Contributing

The AI Science Tracker is meant to be a shared, checkable reference for scientific results obtained with AI. Help is welcome from researchers, domain experts and careful readers.

## Ways to help

- **Suggest a missing discovery.** Use the [discovery form](https://github.com/marcello-pichini/ai-science-tracker/issues/new?template=discovery.yml). Results from outside the large AI labs and from non-English sources are especially welcome.
- **Report a correction.** Use the [correction form](https://github.com/marcello-pichini/ai-science-tracker/issues/new?template=correction.yml) for a wrong date, attribution, number, link or an overstated result. Each entry page also has a "Suggest a correction" link that fills in the entry for you.
- **Review entries in your field.** Check whether the test type and evidence context of an entry match what the source actually shows. Issues labeled [good first issue](https://github.com/marcello-pichini/ai-science-tracker/labels/good%20first%20issue) list concrete review tasks.
- **Propose ideas.** Use [Discussions](https://github.com/marcello-pichini/ai-science-tracker/discussions) for new filters, views, data fields or uses of the dataset.

## What a discovery needs

An entry describes one concrete scientific result in which an AI system played a documented role. It needs:

1. **An original source**: the institution's announcement, the paper or the preprint, not a news aggregator.
2. **A date**: the public announcement date, `YYYY-MM-DD`.
3. **What was shown and how it was tested**, as stated by the source, including its limits.
4. **The AI contribution**, as stated by the source.

Product launches, benchmarks on their own, funding news and general claims about a model's ability are not included. The [methodology](https://marcello-pichini.github.io/ai-science-tracker/methodology.html) explains the selection rules, the test types and the relevance score.

## How suggestions are handled

Suggestions are public and are reviewed before anything changes in the catalog. A maintainer reads the cited source, writes the entry in the catalog's format and links back to the issue. Statements must come from the sources; the catalog does not claim independent verification.

## Contributing code or data directly

Pull requests are welcome. Before opening one:

- Read [docs/discovery-schema.md](docs/discovery-schema.md) for the data format and [docs/DESIGN.md](docs/DESIGN.md) for the design rules.
- Edit `data/discoveries.json` or the page sources only. Files in `share/`, `profiles/`, `og/`, `api/` and the exports are generated: run `python3 scripts/generate_share.py` instead of editing them.
- Run `python3 -m unittest discover -s tests`. All tests must pass.
- Write in English and keep source caveats.

## Licenses

By contributing you agree that data contributions are published under [CC BY 4.0](LICENSE) and code under the [MIT License](LICENSE-CODE).
