# Changelog

Data and format changes to the catalog. Dates are when the change was published. Release `v1.0.0` is archived on Zenodo ([doi:10.5281/zenodo.24217686](https://doi.org/10.5281/zenodo.24217686)).

## 2026-11-15
- Added 478 scientific records and 727 vulnerability cases, excluding unresolved candidates, duplicates and scientific records before 2020. The catalog now contains 839 active scientific entries, 6 archived entries and 735 vulnerability cases. Historical method-only entries and a literature review remain available outside active discovery counts.
- Corrected source, date and model-family attribution; clarified selection and scoring, added annotation-coverage tables and exposed supporting evidence links.
- Improved chart keyboard navigation, result focus, malformed-link recovery and narrow-screen layouts.
- Vulnerability exports now retain classification and remediation caveats. Unknown AI-attribution account dates are `null` in JSON and empty in CSV; disclosure dates remain required.
- Added catalog and Epoch input fingerprints, automatic preview-image freshness checks, and compatible redirects for archive-only profiles. CSV exports neutralize formula prefixes.

## 1.1.0 - 2026-11-14
- Added CSV exports (`data/discoveries.csv`, `data/vulnerabilities.csv`), JSON Schemas (`schema/`), a read-only static API (`api/v1/`) and the Dataset and API page.
- Added an Atom feed (`feed.xml`) of the newest discoveries and vulnerability cases.
- Added four AI-found vulnerability cases (now 8) and one discovery (now 245); added seven paper links (179 of 245 records have one).

## 1.0.0 - 2026-11-14
- First archived release: 244 discoveries, 4 vulnerability cases, model releases from Epoch AI (CC BY 4.0).
