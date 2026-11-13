# AI Science Tracker

Scientific discoveries and artificial intelligence models.

An English-language catalog of scientific results enabled by AI since 2020, with original sources, dates, evidence caveats and editorial relevance scores. A separate model catalog uses Epoch AI data and connects model families to discoveries by name. A family match does not establish which model version was used.

[Browse the site](https://marcello-pichini.github.io/ai-science-tracker/) · [Methodology](https://marcello-pichini.github.io/ai-science-tracker/methodology.html)

## Run locally

```sh
python3 -m http.server 8800 --bind 127.0.0.1
```

Open http://127.0.0.1:8800. The pages fetch JSON, so opening HTML through `file://` will not work.

## Structure

- `index.html`: discoveries, search, filters and charts.
- `models.html`: model releases and discovery links by family.
- `methodology.html`: selection, verification and scoring criteria.
- `styles.css`: shared styling; fonts are hosted locally under `assets/fonts/`.
- `data/discoveries.json`: curated records, documented in `docs/discovery-schema.md`.
- `data/models.json`: generated model data; do not edit manually.
- `scripts/generate_models.py`: Epoch AI import and family linking.

Discovery IDs are stable identifiers: some retain historical Italian slugs so existing links continue to work. New links use `#discovery=ID`; legacy `#scoperta=ID` links remain supported. Model family links use `models.html#fam-ID`.

## Update the data

Add or correct discoveries in `data/discoveries.json`, preserving existing IDs, source links, dates and evidence limitations. Verification means the source was checked; it does not mean the findings were independently replicated.

Download the Epoch AI notable models CSV to `work/epoch/notable_ai_models.csv`, then run:

```sh
python3 scripts/generate_models.py
python3 -m unittest discover -s tests
```

The CSV and research working files are excluded from Git. After updating the input snapshot, update its download date in the generator. Review generated family links before publishing; they are based on names, not independent attribution.

## Attribution and hosting

Model data: [Epoch AI, Data on AI models](https://epoch.ai/data/ai-models), used under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The exported subset, field names and family associations are adapted for this catalog. Original model metrics and names are preserved.

Font: Schibsted Grotesk, distributed under the SIL Open Font License in `assets/fonts/OFL.txt`.

GitHub Pages serves this repository's `main` branch from the root. There is no build step or external JavaScript dependency. Published claims and editorial scores have the limitations described on the methodology page; coverage is manual and incomplete.
