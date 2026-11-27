# Claims schema

`data/claims.json` lists open problems left by catalog discoveries. `scripts/claims/generate_claims.py` builds `claims.html` from it; never edit that page by hand. `tests/test_claims.py` enforces the rules below.

Top level: `about`, `updated` (ISO date), `claims` (array).

Each claim:
- `id`: stable kebab-case slug, also the submissions folder `claims/submissions/ID/`.
- `parent_discovery_id`: an active record in `data/discoveries.json`.
- `title`, `statement`: plain English. Say what the sources report; no new facts.
- `target`: `type` (a key of `CHECKS` in `scripts/claims/verify.py`), `format` (the submission format, shown on the page) and type parameters:
  - `mols-lower-bound`: `baseline_file` (CSV `n,lower,source`).
  - `bin-packing-random-order`: `threshold` (a fraction string), `max_items`.
  - `linear-code-record`: `q`, `n`, `baseline_file` (CSV `q,n,k,lower,upper`), `timeout_seconds`.
- `baseline`: `summary` and `sources` (`label`, `url`, and an optional `date` of publication or `checked` date of the last lookup).
- `caveat`: the limit of what a passing check means.
- `status`: `open`, `claimed`, `submitted`, `solved` or `retired`. Only a maintainer sets `solved`, after a passing check and a literature check.
- `added_date`: ISO date.
- `attempts[]`: `handle` (GitHub), `agent`, `model`, `date`, `outcome` (`released`, `submitted`, `rejected`, `verified`), `reason` when released (`no_improvement`, `out_of_time`, `statement_seems_false`, `too_hard`, `other`), `summary`.

Live claims are GitHub issues labelled `claim`. The `Claims` workflow checks submission pull requests with the base branch's checker and closes claims inactive for 30 days.

A new problem needs a target that a program can decide. A new target type needs a checker in `verify.py` with tests.
