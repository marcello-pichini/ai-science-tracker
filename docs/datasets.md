# Component snapshots and exact entity aliases

`python3 scripts/generate_share.py` writes `api/v1/manifest.json` after collection CSV generation. The manifest covers every current collection JSON/CSV, including archived science, model progress, separately licensed SWE-bench, OpenAlex citations reviewed entity aliases, all separately licensed numerical benchmark components/their directory and the catalog-summary CSV. Components retain their own units, sources, dates and licenses. Counts are catalog units, not independent findings or unique models. The manifest is not an acquisition census or a claim of corpus-wide scientific review.

Each descriptor contains the exact file path, byte length and SHA-256 of its UTF-8 bytes. Whitespace changes affect this hash. `snapshot_sha256` hashes the complete descriptors using UTF-8 JSON, sorted keys and compact separators; it contains no run-clock timestamp. The manifest does not hash itself, generated HTML or API index. Identical final inputs produce identical output. `api/v1/index.json` links this manifest additively; the older four-input normalized `catalog_sha256` and latest-addition date alias retain their original meanings.

Source dates retain their meanings: scientific publication versus addition; vulnerability disclosure versus AI attribution versus catalog source-check; notable-model generation versus recorded source download; progress retrieval versus model recorded dates; SWE retrieval versus evaluation dates; citation metadata check. Unknown dates are null. Filesystem times are not source or review dates. Archive/release links do not assign new upstream DOIs. The catalog concept DOI cites the catalog archive.

## Runtime consistency

`assets/catalog-data.js` requests a cache-distinct manifest, then hash-versioned collection URLs. Native SHA-256 validates the exact bytes before JSON decoding and parsing. A second fresh manifest read detects deployment drift. A mismatch discards the complete attempted set; one whole-set retry is allowed. Persistent errors show recovery links and a manual Retry button. Required component failures do not fall back to unversioned data, old local storage or partial search results.

Discoveries/profile load science, model families, citations, archives and entity aliases together. Search loads its four collections and aliases together. Security loads its cases and aliases together. Model progress, SWE and the additional benchmark directory/components load from one shared promise while remaining separately counted/licensed. Benchmark component IDs are resolved from the same manifest attempt, including on retry; every actual loaded component hash is observable. The additional metric renderer receives these validated objects and discards private state on failure, without an independent network cache. Methodology's coverage derives from verified science bytes. Dataset comparison reads manifest metadata rather than independently re-fetching every collection.

After the returned data is rendered, `document.documentElement` exposes:

- `data-load-state="ready"`;
- `data-snapshot-sha256`, the manifest identity actually used;
- `data-component-sha256`, a JSON map of validated loaded component IDs/hashes;
- `data-page-snapshot`, the generated HTML shell's expected snapshot, when generated.

The visible status links the manifest. A stale HTML shell using a coherent newer data set is identified explicitly. Browser verification must inspect these attributes and rendered changed records, not merely fetch a separate API. Already-open tabs running older loader code cannot be repaired retroactively. Integrity/coherence checks do not authenticate a compromised origin or establish when a CDN became current. Use HTTPS or localhost for native secure hashing; unsupported contexts show a useful failure.

## Reuse terms

Science/security catalog content and entity aliases are CC BY 4.0. Epoch model collections retain Epoch AI CC BY 4.0 attribution. OpenAlex citation metadata is CC0 and selectively matched; it is not an evidence-quality score. SWE-bench retains **CC BY-NC 4.0**, source attribution, transformation notice and exact evaluation configurations. It is for noncommercial reuse only and remains excluded from the current unrestricted Hugging Face catalog export. Repository/Zenodo source archives containing it must retain this exception; the entire archive is not uniformly CC BY 4.0. See [SWE-bench terms and interpretation](swe-bench.md).

## Exact entity aliases

`data/entity-aliases.json` is a reviewed sidecar; discovery `organization` and security `ai_system` source strings remain unchanged. Python `scripts/entities.py` and browser `assets/catalog-entities.js` consume the same map. Semicolons separate organizations; commas/conjunctions within names remain literal. Only the first affiliation contributes to organization aggregates. Unknown affiliation has its own group and is excluded from institution counts/directories, retaining original author/source wording on records.

The initial reviewed aliases group MIT/Massachusetts Institute of Technology, supported by the official MIT about page. Exact AISLE labels group under a source-attributed vendor ID, supported by a cited AISLE platform disclosure. The bounded alias review on 18 November 2026 does not establish exact models/versions, autonomy, independent reproduction or a comparative-effectiveness ranking. Unlisted labels remain literal/unreviewed; there are no fuzzy joins or inferred model identities. Historical organization URLs are preserved by the profile generator, with ambiguity routed to the directory.

## Review preflight

Run this read-only comparison before applying a source-review/enrichment patch:

```sh
python3 scripts/validate_review_patch.py --before BEFORE.json --after AFTER.json
```

A newly added/changed `source_review`, or a transition into source-checked status, requires an actual ISO review day and nonempty bounded material-read scope; future dates are rejected. Untouched historical missing review metadata remains valid. Scientific wording edits alone do not invent review metadata. The preflight validates documented provenance fields; actual source reading and scientific admission remain editorial responsibilities. It does not authenticate a claimed reading or turn abstract access into full-text access.

`data/catalog-summary.csv` counts overlapping year/field aggregate rows, not discoveries. Each grouping separately reconciles to active entries; never add year and field group totals together. The existing static comparison links the finer field/year acquisition and source-review-gap table. Numerical sources retain their individual CC BY 4.0, CC BY-SA 4.0, MIT or Apache-2.0 terms in the manifest, matrix and Dataset graph; no blanket catalog license applies.
