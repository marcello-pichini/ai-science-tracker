# Model progress

The page also exposes [ten independent numerical benchmark components](public-benchmarks.md), each with its own attribution, license, source revision, selection and interpretation limits. They are separate from the ECI pair chart and are not joined to Epoch model labels. Several are historical snapshots. The daily workflow now checks all ten exact selections, validates source rights and supported formats, and retains each previous snapshot with a visible warning if its source is blocked. The existing SWE-bench Verified component retains its separate CC BY-NC 4.0 terms.

`model-progress.html` compares exact source model entries across OpenAI, Google DeepMind, Anthropic, Meta, Alibaba, DeepSeek, xAI and Mistral. It complements `models.html`; it does not change discovery counts, family attribution or the original model catalog.

## Reproduce the data

Download the public [Epoch AI benchmark export](https://epoch.ai/data/benchmark_data.zip) to a private working directory, then run:

```sh
python3 scripts/import_model_progress.py /private/path/benchmark_data.zip --fetched-on 2026-11-16
```

The importer defaults to `data/models.json` and writes `data/model-progress.json`. `--catalog` and `--output` accept alternate paths. The retrieval date must reflect the actual download. The ZIP and raw CSV files remain private and must not be committed. No local input paths are written to the output. Attribution: [Epoch AI](https://epoch.ai/benchmarks), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Output retains the ZIP SHA-256 and the notable-model catalog's source CSV hash.

The 16 Nov 2026 snapshot contains 569 entries, 207 with ECI, across eight labs. A repeated import against the same inputs is byte-identical. Dates used for the rolling chart and cadence window come from the export retrieval date.

## Identity and evidence

The union retains all attributed source model groups and existing requested-lab catalog releases, including entries without ECI. A catalog label joins a source group only when its normalized alias identifies one source-provided group and its date matches a metadata date. Original catalog labels, dates and links are preserved. No speculative product aliases are added. Source model groups, aliases and catalog labels can overlap; entry counts do not establish a count of independent generations. Astra, Sol, Terra and Luna remain distinct exact source entries.

Where organizations are empty, the importer explicitly flags family-name attribution (26 entries in this snapshot). Ambiguous multi-lab ownership is excluded rather than silently assigned. The scope is the selected sources and attribution rules, not every real-world launch.

ECI is an arbitrary composite point scale, not an accuracy percentage. Source-provided 90% credible intervals appear where available; missing intervals are not estimated. Interval overlap does not prove equality or a reliable ranking, and interval separation is not a joint probability or significance test for a difference.

The four raw benchmark files provide percentage scores. Each model's best observed configuration is displayed, with all imported configurations retained in JSON and the winning configuration identified on the page. Models can have different settings and inference budgets; this is not a matched-budget experiment. Missing scores are absent observations, never zero. Zero scores remain valid.

Benchmark release dates take priority; catalog publication dates fill gaps. Recorded-date gaps do not establish verified launch intervals or generational lineage. Same-day entries count as one cadence event. The page exposes date definitions, exact source labels, source-export links and original catalog sources where available. It makes no claim about scientific productivity, causal model progress or universal superiority. Token pricing is omitted because the prototype's sampled prices lacked retained source provenance.

## Maintenance and checks

The page uses only `styles.css`, self-hosted fonts, inline SVG and native controls. `assets/model-progress-facts.js` contains the descriptive comparison calculation; `assets/model-progress.js` renders charts, inventory, filters, presets, readout and date inspection. Both script URLs carry content hashes; refresh those URLs whenever their bytes change. Shared CSS hash maintenance follows the site's existing workflow.

Run `python3 -m unittest discover -s tests -p test_model_progress.py` for focused coverage, then the complete repository suite and the standard light/dark desktop/375/320 px browser checks. Snapshot totals in the focused test must be deliberately updated after a reviewed new import. Review import assertions and source-schema changes rather than dropping unmapped entries silently. Independent benchmark reproduction, formal pairwise statistical inference, real-device testing and human comprehension testing are outside these checks.

Exact-entry links accept `model-progress.html?model=ENCODED_SOURCE_ID`. An entry-only link selects its lab and a distinct same-lab baseline where possible, preferring an earlier scored entry. It expands to full history when either selected date is outside the recent window. Unknown model IDs leave the default comparison intact. Current `model`, `baseline`, `lab` and `period` selections are written into the URL without dropping other query parameters. Explicit pairs, empty baselines, cross-lab comparisons and period choices survive sharing; these URLs describe chosen comparisons, not documented model lineage.
