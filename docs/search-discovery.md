# Search discovery and evidence pages

The site exposes its catalog through existing field/year collections, a reproducible coverage comparison and source-attributed security case pages. These improve navigation and access without JavaScript; they do not guarantee indexing, rankings or traffic.

Run `python3 scripts/generate_share.py` after changing discovery/security data or relevant templates. `--no-images` preserves existing images and skips Chrome when no preview changes are required. Generated files must not be edited by hand.

## Generated destinations

- `profiles/field-*.html` and `profiles/year-*.html`: collection counts, structured-annotation coverage, scope limitations and links to complete year/field collections. Cross-link counts refer to the current selection; the linked destination is the full collection.
- `profiles/catalog-evidence.html`: current active discovery composition by year and field. It excludes archived discoveries, model releases and security cases.
- `data/catalog-summary.csv`: the exact comparison table rows, with `grouping`, `group`, `catalog_entries`, `evidence_annotated` and `source_checked` columns. Year uses `publication_date[:4]`; annotation presence means a nonempty `evidence` object; source checked means `verification_status == 'verified'`. Each grouping separately sums to the active catalog size. The two groupings must not be added together.
- `profiles/vulnerabilities-SLUG.html`: one overview page per product category of the global vulnerability dataset with at least 20 vulnerabilities (counts, top products, yearly trend, recent preview entries). The retired AI-case pages `profiles/security-*.html` are noindex redirects to `security.html`.

Category pages use the security Dataset identity at `dataset.html#security-dataset`; vulnerabilities do not belong to the scientific-discovery dataset.

The comparison describes catalog coverage and editorial annotation effort. It is not a census of science, a count of independent findings, a field-productivity ranking or a measure of AI effectiveness. Annotation presence and source checking are distinct, overlapping attributes; neither establishes independent replication or clinical benefit.

For stable citations, select a matching archived Zenodo release and state its version. The current site, comparison and CSV change when the underlying catalog changes. Scientific claims should cite their original sources.
