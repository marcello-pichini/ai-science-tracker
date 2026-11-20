# Site and dataset monitoring

`Site and dataset checks` runs on GitHub Actions after `Publish datasets` completes
and daily at 07:15 UTC. It is independent of the maintainer's computer and needs
no AI API or new secret. A manual run can also request the full external-link scan.

The workflow selects the latest successful main-site deployment and checks against
that exact Git commit. Separately, freshness compares the expected main update SHA
with the deployed SHA, so selecting an older successful deployment cannot hide lag.
Monitoring tools run from main; the expected published snapshot is checked out
separately. The checks are read-only and never modify catalog records or retry a
publication automatically.

## Publication checks

- Core pages, the profile directory and one discovery share page must be reachable
  and contain a title and main heading.
- Referenced same-origin scripts and styles must match the deployed source bytes.
- Live scientific, vulnerability and model JSON plus the API index must match the
  deployed source contents. Optional benchmark collections are checked when present.
- When present, `api/v1/manifest.json` and every component it lists must match
  the deployed snapshot byte for byte. Conflicting hashes in the catalog manifest
  and benchmark registry fail the check.
- `data/benchmarks/index.json` is required and compared with the deployed snapshot.
  Every numerical component listed there is checked against its exact SHA-256, even
  when the catalog component manifest is absent. Unsafe paths, invalid registries,
  missing files and invalid hashes fail the check. Historical snapshots
  predating the registry require explicit `--allow-legacy-benchmarks` opt-in.
- Hugging Face's four scientific/vulnerability JSON and CSV files must match that
  same snapshot, comparing actual contents rather than just record counts.
- The Zenodo concept DOI must resolve to the latest GitHub release version. A new
  release has a two-hour archival grace period, reported as pending, not passed.
  Later checks fail if the version remains missing. Zenodo checks version metadata;
  they do not download or certify the full archive ZIP.

These are HTTP, HTML and content checks, not a browser rendering, accessibility or
scientific-evidence audit. An unchanged Epoch export is not considered stale merely
because its retrieval date is old.

## Deployment freshness metadata

Pass `--deployment-metadata deployment.json` alongside the expected deployed tree.
The JSON object contains `expected_sha` (current expected main commit),
`deployed_sha` (latest successful Pages commit), and `expected_updated_at` (the
expected commit's ISO 8601 timestamp with timezone). Both SHAs must be full lowercase
40-character values. Optional `grace_seconds` defaults to 7200. Different SHAs are
`pending` inside the grace period and `fail` at or beyond its boundary; equal SHAs
pass. Missing/invalid timestamps or identities fail rather than implying freshness.
The report preserves the supplied metadata and a separate `deployment/freshness`
result. Omitting the option performs content parity only and establishes no
freshness claim. Grace covers deployment propagation, not an old benchmark retrieval
date or upstream source availability.

## External source links

On Monday's daily run, `scripts/check_links.py` scans and deduplicates the original
source, paper, AI-attribution and advisory URLs. A 404 or 410 must be confirmed by
a second request before being reported as missing. Access blocks (including 403),
rate limits, redirects that do not resolve, timeouts and server errors are reported
as inconclusive; they do not establish that a source disappeared. The scanner
limits concurrency and request duration. It never deletes or replaces a citation.

## Reports and alerts

Each run writes a readable job summary and JSON reports to the
`monitoring-reports` artifact, retained for 30 days. Confirmed publication mismatches
or missing links fail the workflow. GitHub delivers failure notifications according
to the account's existing Actions notification settings; no new email sender,
mailing list, public issue or third-party alert service is configured.
