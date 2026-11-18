# Site and dataset monitoring

`Site and dataset checks` runs on GitHub Actions after `Publish datasets` completes
and daily at 07:15 UTC. It is independent of the maintainer's computer and needs
no AI API or new secret. A manual run can also request the full external-link scan.

The workflow selects the latest successful main-site deployment and checks against
that exact Git commit, rather than unpublished changes on main or a local checkout.
Monitoring tools run from main; the expected published snapshot is checked out
separately. The checks are read-only and never modify catalog records or retry a
publication automatically.

## Publication checks

- Core pages, the profile directory and one discovery share page must be reachable
  and contain a title and main heading.
- Referenced same-origin scripts and styles must match the deployed source bytes.
- Live scientific, vulnerability and model JSON plus the API index must match the
  deployed source contents. Optional benchmark collections are checked when present.
- Hugging Face's four scientific/vulnerability JSON and CSV files must match that
  same snapshot, comparing actual contents rather than just record counts.
- The Zenodo concept DOI must resolve to the latest GitHub release version. A new
  release has a two-hour archival grace period, reported as pending, not passed.
  Later checks fail if the version remains missing. Zenodo checks version metadata;
  they do not download or certify the full archive ZIP.

These are HTTP, HTML and content checks, not a browser rendering, accessibility or
scientific-evidence audit. An unchanged Epoch export is not considered stale merely
because its retrieval date is old.

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
