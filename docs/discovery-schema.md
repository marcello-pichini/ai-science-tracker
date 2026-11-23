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
| `organization` | string | Affiliations announcing the result, separated with semicolons. Preserve commas and conjunctions inside institution names; the first complete affiliation supplies the organization grouping. |
| `source_url` | URL | Original paper or preprint, or an announcement by the institution responsible for the work. |
| `source_type` | string | `press release`, `blog`, `paper` or `other`. |
| `publication_date` | date | Documented announcement or paper-version publication date, `YYYY-MM-DD`; explain version differences in the summary. |
| `added_date` | date | Date added to the catalog. |
| `verification_status` | string | `verified` or `needs verification`. |
| `paper_url` | URL | Paper or preprint; may be empty. |
| `search_title` | text | Optional, hand-reviewed short title (≤65 characters) used only for the share page `<title>`. When absent the generator clips `title` at a word boundary and appends the field. The heading, Open Graph title and JSON-LD keep the full `title`. |
| `relevance` | object | `impact`, `validation`, `novelty`: integer scores 1–5. |
| `evidence` | object | Optional evidence description and catalog test category. `publication_status` (`Peer-reviewed paper`, `Preprint`, `Announcement only`, `Not reported`), `tested`, `unknown`, `ai_role` (short text), `evidence_urls` (https pages actually read) and `test_type` (`not reported`, `retrospective or benchmark`, `direct test`, `prospective or independent check`, `replication or operational use`). When `test_type` is present it sets `relevance.validation` (1–5 in that order). The test category is an editorial classification under the precedence rules in methodology.html, not a source-assigned quality grade. Other scientific statements must be supported by the cited sources and are never inferred from the relevance score. The category changes validation and therefore can change the displayed score; impact and novelty are separate judgments. Review limitations are explicitly labeled; see below for legacy `Not reported` values. |

Categories: `biology`, `chemistry`, `medicine`, `materials`, `climate`, `mathematics`, `physics`, `astronomy`, `computer science`, `humanities`, `multidisciplinary`, `other`.

Use `astronomy` when the principal result concerns celestial objects or phenomena, planetary science, or instrumentation and methods developed for astronomical observations. Use `physics` for results centered on fundamental physical laws or general physical systems.

The displayed score is `min(round((impact + validation + novelty) / 3 × 20), (validation + 1) × 20)`. It ranges from 20 to 100 with thirteen possible values (20, 27, 33, 40, 47, 53, 60, 67, 73, 80, 87, 93, 100); under an active cap a subscore increase may change the result by zero. The cap constrains the influence of impact and novelty, not universal ordering by evidence strength. This is a coarse editorial judgment, not an objective measure, evidence grade or reliable cross-field ranking. JavaScript `CatalogUI.score` and Python `scripts/generate_share.py:score` must agree. Change impact and novelty only with documented record-level review.

For `test_type`, existing-data evaluation takes precedence over words such as prospective collection or independent cohort: neither establishes new prospective evaluation of a frozen model. Initial experimental screening within the discovery study is a direct test, including contracted assays. Level 4 requires prospective evaluation before new outcomes in the intended workflow, a separate research team's follow-up confirmation, or formal proof-kernel checking of the encoded theorem (not a claim of human review); level 5 requires repeated confirmation or documented sustained operational outcomes. Classify the represented claim, describe ancillary experiments separately, and preserve uncertainty when timing or independence is not established. See Methodology for the full rules.

## Inclusion and counting unit

An entry needs a specific source-described scientific, clinical or field result and an explanation of AI's contribution. Original papers and preprints are permitted alongside institutional announcements; source type does not establish peer review or independent confirmation. General method or representation benchmarks alone do not qualify. A retrospective diagnostic-validation study can qualify as a specific clinical study without establishing clinical benefit or new biology; prospective testing is not required in every scientific field. A borderline method's summary must identify the qualifying result and preserve its limits.

Counts measure active catalog entries, not independent findings. Keep one entry for a coherent result or bundle from an announcement. Split only when distinct source-supported scientific results each have their own AI contribution and limitations. If two active entries share a normalized DOI, document the distinct results through a `shared evidence` relationship. Later announcements and paper versions about the same result normally update the existing entry, noting version differences. Methods and applications can overlap in the underlying result; disclose such overlap rather than implying independent discoveries. Preserve historical IDs and links. Archive a duplicate with a `same result` relationship to the retained entry. Link a predecessor paper through the relationship to the earlier result so its citation metrics apply to that result. This policy does not imply that all historical overlaps have been resolved.

## Evidence annotation limits

An absent `evidence` object means unannotated in this catalog, not absent evidence. Its presence is counted as annotation coverage even when some fields are unspecified. Publication status is not inferred for unannotated entries, and primary-source composition is not an evidence-quality measure.

For new or revised free-text fields, distinguish `Not assessed` (material not reviewed or inaccessible), `Not stated in the reviewed material` (the pages read omit the detail), and a scientific unknown explicitly attributed to a cited source. Use `Not applicable` only with an explanation. Do not infer absence from an inaccessible paper or scientific uncertainty from an omitted detail. The earlier pilot's `Not reported` values are ambiguous annotation gaps, retained until review. The publication-status enum is unchanged; if it remains `Not reported`, explain any relevant review limitation in the free text rather than inventing a publication status.

When reviewing an entry, record the actual scope (announcement, abstract or full paper) and actual review date in the review record. `source_review: {date, scope}` optionally records the actual day and bounded material reviewed; absent fields mean unknown scope/date. Do not treat `publication_date` or `added_date` as review dates or invent historical checks. `verified` means source checked for the entry's stated claims, not independent scientific confirmation; a linked paper does not by itself establish that its full text was read.

## Model data

`data/models.json` is generated by `scripts/generate_models.py` from the Epoch AI CSV. Top-level keys are `generated`, `source`, `models`, `families`, `linked_discoveries`.

- `source`: `name`, `url`, `license`, `license_url`, `csv_sha256`, `original_records`. The fingerprint identifies the input snapshot; it does not establish a download date.
- Each model: `name`, `organization`, `date`, `domain`, `parameters`, `compute_flop`, `access`, `frontier`, `link`, `family`.
- Each family: `id`, `name`, `discoveries`, `models`, `discovery_count`, `model_count`.

Family discovery lists contain discovery IDs, while model lists contain model names. A match identifies a family, not a specific version used in an experiment. Preserve the Epoch AI attribution and CC BY 4.0 license when reusing this data.


## Optional source review, follow-up and relationships (IMP-005/006/010/027)

These fields describe recorded evidence, never automatic score changes or new discovery counts. They are retained in JSON/API and serialized as JSON cells in CSV; evidence publication status, test type, tested result, unknowns, AI role and source URLs also have CSV columns.

- `source_review`: `{date: "YYYY-MM-DD", scope: "material actually reviewed"}`. State the reviewed material directly. Preserve dates from recorded reviews and avoid substituting publication or addition dates.
- `follow_up_review`: the same date/scope structure for a bounded follow-up search. An absent review is unknown; no events means “No follow-up recorded”, not that no follow-up exists.
- `follow_up`: array of `{id, kind, date, date_precision, note, source_urls, recorded_date}`. IDs are stable safe slugs unique within the record. Kinds: `publication`, `same-team extension`, `independent follow-up`, `documented application`, `contradiction`, `correction`, `retraction`. `date_precision` is `year`, `month`, `day` or `unknown`, matching `YYYY`, `YYYY-MM`, `YYYY-MM-DD` or null respectively. `recorded_date` is the actual recording day. Each bounded note and event kind needs nonempty HTTPS `source_urls`. A journal version is not replication; important corrections must also update the current summary.
- `relationships`: directed array of `{type, target_id, reason, source_urls}`. Types: `same result`, `extends`, `independent follow-up`, `shared evidence`. Read as “this entry [type] target”; `same result` and `shared evidence` assert the stated relation without merging records. Targets must be existing active or archived IDs, never self-links; duplicate type/target pairs are invalid. A bounded reason and nonempty HTTPS sources are mandatory. Links are curated, not inferred from similar names, shared organizations or fields.

The generator validates these optional structures before writing outputs. Missing evidence is displayed as “Not annotated in this catalog”; legacy `not reported` test categories and `Not reported` publication categories remain distinct unspecified annotations. Neither label establishes absent scientific evidence.

New source-review patches must pass `python3 scripts/validate_review_patch.py --before BEFORE.json --after AFTER.json`. Only actually changed review metadata or transitions into source-checked status require a documented actual review day/scope; untouched unknown historical metadata stays valid. This is a workflow check, not proof of source reading. Exact entity aliases and component snapshot dates are described in [datasets.md](datasets.md); original record labels are preserved.
