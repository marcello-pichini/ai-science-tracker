# Design and consistency rules

Every page, script and generated asset must look and behave like one product. These rules apply to every contributor, human or model. `python3 -m unittest discover -s tests` enforces the mechanical ones (`tests/test_design.py`).

## Identity

- Idea: a cyanotype, the Prussian-blue print used in early scientific atlases. One strong blue banner per page; everything else quiet, light and typographic.
- Typeface: Schibsted Grotesk only, self-hosted in `assets/fonts/`. No other fonts, no external requests.
- Light and dark themes both ship. Never test or design for one only.

## Single stylesheet

- All styling lives in `styles.css`. Pages have no `<style>` blocks and no `style=""` attributes, except for data-driven values (a bar width, an animation delay, a CSS variable).
- All colors come from the custom properties in `:root` (`--prussia`, `--paper`, `--sheet`, `--ink`, `--ink-2`, `--muted`, `--line`, `--line-2`, `--accent`, `--accent-wash`, `--sole`, ...). Never write a hex color, `rgb()` or named color outside `:root` and its two dark-mode blocks. If a new color is truly needed, add a variable with a light and a dark value.
- Spacing, radii, type scale and widths reuse existing values (`--wrap`, `--gut`, `--r`, the `clamp()` sizes already in use). Do not invent near-duplicates.
- Reuse existing component classes before adding any: header and menu, banner (`.banda`), section (`.sez`), chart panels, filter bar, discovery entry (`.voce`), tag (`.etich`), badge, family card, release table, long-form text (`.prosa`), footer. A new page is assembled from these.
- A new component needs: a short comment in `styles.css`, light and dark appearance, a keyboard focus state, a layout at 320 px, and a print appearance.

## Page skeleton

Every page has the same frame, in this order: shared `<head>` (charset, viewport, title `Page · AI Science Tracker`, description, Open Graph, canonical, theme color, icon, font preload, `styles.css` with its content-hash query), the header with the five-item menu (Discoveries, Models, Vuln discoveries, Methodology, Guide) plus the page's own `aria-current="page"`, a blue banner with one `<h1>`, `<main>` with sections that each have an `<h2>`, and the footer. Copy the frame from an existing page; do not retype it. `404.html` is the one exception to the shared `<head>` (no canonical or Open Graph, `noindex`, and a `<base href>` so it works from any URL depth); `tests/test_site_links.py` checks it instead of `PAGES`.

## Charts and interaction

- Charts are hand-written inline SVG, no libraries, using the existing chart classes. One mark per datum, a tooltip via the shared tip pattern, keyboard operation, and a text alternative (`aria-label` or a "View data as a table" block).
- Clicking a chart element filters the list below; clicking again clears it. Keep that behavior everywhere. Security charts use the existing bar-row component with fully wrapped source labels; its reading guide and chart panels are optional disclosures, with immediate banner links to cases and charts.
- Motion is short and respects `prefers-reduced-motion`.

## Language and tone

- All visible text, code identifiers, comments, filenames and documentation are in English. Dates render as `4 Nov 2026` (`en-GB`).
- Plain, neutral wording. Say what a source reports; never claim independent verification. Keep evidence caveats.

## Accessibility and performance

- Semantic landmarks, visible focus, contrast that holds in both themes, `aria-live` for result counts, no information carried by color alone.
- No external scripts, fonts, trackers or CDNs. The site is static files served by GitHub Pages; JSON is fetched from `data/`.
- Pages must work at 320 px without horizontal scrolling.
- Long record lists may defer offscreen layout with `content-visibility:auto`; keep the first four records eager, estimate only intrinsic height, and restore full layout in print. Initial catalog and model summaries are generated from the data to avoid loading shifts.

## Links and sharing

- Discovery link: `index.html#discovery=ID`. Shareable (social preview) link: `share/ID.html`, generated. Profiles: `profile.html?org=NAME` and `profile.html?family=ID`. Filters live in the query string of `index.html`.
- Generated files (`share/`, `og/`, `api/`, `feed.xml`, `data/*.csv`, `sitemap.xml`, `llms.txt`, `data/models.json`) are never edited by hand: change the generator and rerun it.

## Before you finish

1. `python3 -m unittest discover -s tests`
2. Open every page you touched in light and dark, at 1280 px and 375 px, and check the console is empty.
3. Update `NOTES.md` and, if you changed a rule, this file.
