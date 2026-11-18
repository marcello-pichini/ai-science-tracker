# Search discovery and evidence pages

The site exposes its catalog through existing field/year collections, a reproducible coverage comparison and source-attributed security case pages. These improve navigation and access without JavaScript; they do not guarantee indexing, rankings or traffic.

Run `python3 scripts/generate_share.py` after changing discovery/security data or relevant templates. `--no-images` preserves existing images and skips Chrome when no preview changes are required. Generated files must not be edited by hand.

## Generated destinations

- `profiles/field-*.html` and `profiles/year-*.html`: collection counts, structured-annotation coverage, scope limitations and links to complete year/field collections. Cross-link counts refer to the current selection; the linked destination is the full collection.
- `profiles/catalog-evidence.html`: current active discovery composition by year and field. It excludes archived discoveries, model releases and security cases.
- `data/catalog-summary.csv`: the exact comparison table rows, with `grouping`, `group`, `catalog_entries`, `evidence_annotated` and `source_checked` columns. Year uses `publication_date[:4]`; annotation presence means a nonempty `evidence` object; source checked means `verification_status == 'verified'`. Each grouping separately sums to the active catalog size. The two groupings must not be added together.
- `profiles/security-index.html` and `profiles/security-ID.html`: every current public security case, linked to the interactive tracker and its JSON record. The generator preserves separate disclosure, attribution and source-check dates, AI/human contribution, CVEs, remediation scope and attributed severity/impact evidence. Missing evidence remains unknown.

The static security generator reuses the severity/evidence functions from `security.html` through one Node rendering call. Missing renderer declarations are an error, rather than permission to omit evidence. Generated case metadata uses a separate security Dataset identity at `dataset.html#security-dataset`; cases do not belong to the scientific-discovery dataset. Case pages use WebPage metadata, without fabricated publication or modification dates.

The comparison describes catalog coverage and editorial annotation effort. It is not a census of science, a count of independent findings, a field-productivity ranking or a measure of AI effectiveness. Annotation presence and source checking are distinct, overlapping attributes; neither establishes independent replication or clinical benefit.

For stable citations, select a matching archived Zenodo release and state its version. The current site, comparison and CSV change when the underlying catalog changes. Scientific claims should cite their original sources.
