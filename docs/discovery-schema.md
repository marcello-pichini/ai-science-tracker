# Discovery data schema

`data/discoveries.json` is an array of records. Text is in English; source titles may be translated. IDs are stable and may retain historical slugs.

`data/archived-discoveries.json` uses the same record schema for entries excluded from the active catalog after editorial review. Its summaries explain the exclusion. Archived IDs must be unique and absent from the active array; their historical share pages remain available, but they do not contribute to discovery counts, profiles, model-family associations, feeds, CSV exports or the active API.

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Unique, stable identifier. |
| `title` | string | Concise description faithful to the source. |
| `summary` | string | Findings, attribution and evidence limitations. |
| `field` | string | One of the categories below. |
| `ai_technology` | string | Named model or AI method; may be empty. |
| `organization` | string | Organization(s) announcing the result. |
| `source_url` | URL | Original paper or preprint, or an announcement by the institution responsible for the work. |
| `source_type` | string | `press release`, `blog`, `paper` or `other`. |
| `publication_date` | date | Documented announcement or paper-version publication date, `YYYY-MM-DD`; explain version differences in the summary. |
| `added_date` | date | Date added to the catalog. |
| `verification_status` | string | `verified` or `needs verification`. |
| `paper_url` | URL | Paper or preprint; may be empty. |
| `relevance` | object | `impact`, `validation`, `novelty`: integer scores 1–5. |
| `evidence` | object | Optional, pilot only. `publication_status` (`Peer-reviewed paper`, `Preprint`, `Announcement only`, `Not reported`), `tested`, `unknown`, `ai_role` (short text) and `evidence_urls` (https pages actually read). Scientific statements must be stated by those sources; they are never inferred from the website, keywords or the relevance score and do not change the score. Review limitations are explicitly labeled; see below for legacy `Not reported` values. |

Categories: `biology`, `chemistry`, `medicine`, `materials`, `climate`, `mathematics`, `physics`, `computer science`, `humanities`, `multidisciplinary`, `other`.

The relevance score is the rounded mean of the three integer criteria multiplied by 20: 20–100 with thirteen possible values (20, 27, 33, 40, 47, 53, 60, 67, 73, 80, 87, 93, 100). It is a coarse editorial judgment, not an objective measure, evidence grade or reliable cross-field ranking. See `methodology.html` for all 1–5 anchors and the prospective calibration process. Existing scores have not all been recalibrated; preserve them unless a documented record-level review supports a change. Keep source-stated evidence context separate from the rationale for editorial scores.

## Inclusion and counting unit

An entry needs a specific source-described scientific, clinical or field result and an explanation of AI's contribution. Original papers and preprints are permitted alongside institutional announcements; source type does not establish peer review or independent confirmation. General method or representation benchmarks alone do not qualify. A retrospective diagnostic-validation study can qualify as a specific clinical study without establishing clinical benefit or new biology; prospective testing is not required in every scientific field. A borderline method's summary must identify the qualifying result and preserve its limits.

Counts measure active catalog entries, not independent findings. Keep one entry for a coherent result or bundle from an announcement. Split only when distinct source-supported scientific results each have their own AI contribution and limitations, and explain their relationship. Later announcements and paper versions about the same result normally update the existing entry, noting version differences. Methods and applications can overlap in the underlying result; disclose such overlap rather than implying independent discoveries. Preserve historical IDs and links. This policy does not imply that all historical overlaps have been resolved.

## Evidence annotation limits

An absent `evidence` object means unannotated in this catalog, not absent evidence. Its presence is counted as annotation coverage even when some fields are unspecified. Publication status is not inferred for unannotated entries, and primary-source composition is not an evidence-quality measure.

For new or revised free-text fields, distinguish `Not assessed` (material not reviewed or inaccessible), `Not stated in the reviewed material` (the pages read omit the detail), and a scientific unknown explicitly attributed to a cited source. Use `Not applicable` only with an explanation. Do not infer absence from an inaccessible paper or scientific uncertainty from an omitted detail. The earlier pilot's `Not reported` values are ambiguous annotation gaps, retained until review. The publication-status enum is unchanged; if it remains `Not reported`, explain any relevant review limitation in the free text rather than inventing a publication status.

When reviewing an entry, record the actual scope (announcement, abstract or full paper) and actual review date in the review record. Structured review-scope/date fields are not implemented; do not treat `publication_date` or `added_date` as review dates or invent historical checks. `verified` means source checked for the entry's stated claims, not independent scientific confirmation; a linked paper does not by itself establish that its full text was read.

## Model data

`data/models.json` is generated by `scripts/generate_models.py` from the Epoch AI CSV. Top-level keys are `generated`, `source`, `models`, `families`, `linked_discoveries`.

- `source`: `name`, `url`, `license`, `license_url`, `csv_sha256`, `original_records`. The fingerprint identifies the input snapshot; it does not establish a download date.
- Each model: `name`, `organization`, `date`, `domain`, `parameters`, `compute_flop`, `access`, `frontier`, `link`, `family`.
- Each family: `id`, `name`, `discoveries`, `models`, `discovery_count`, `model_count`.

Family discovery lists contain discovery IDs, while model lists contain model names. A match identifies a family, not a specific version used in an experiment. Preserve the Epoch AI attribution and CC BY 4.0 license when reusing this data.
