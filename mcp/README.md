# AI Science Tracker MCP

This read-only Streamable HTTP Worker exposes `search_discoveries` and `get_discovery`. It uses the public discovery catalog and per-record API at `aisciencetracker.org`. The catalog remains maintained and hosted by the existing GitHub Pages workflow.

The configured production endpoint is `https://mcp.aisciencetracker.org/mcp`. An MCP client connects directly to that URL. It does not need a token.

```sh
codex mcp add ai-science-tracker --url https://mcp.aisciencetracker.org/mcp
```

Tools: `search_discoveries`, `get_discovery` and `list_fields`.

Search supports optional terms, publication year, field, organization, result limit and offset, and reports the total number of matches. Each result carries a stable ID, a short summary, the original source and the catalog link. Each term must match the start of a word in the title, field, organization, AI technology or summary (so `whale` finds `whales`, but `ants` does not find `variants`); terms of three letters or fewer must match a whole word (`ml` does not find `mlp`). Query plurals are folded (`antibiotics` also finds `antibiotic`), and common filler words (`how`, `new`, `for`) and `AI` itself, which every record shares, are ignored. When no record matches every term of a query with three or more terms, the records matching most of them are returned and flagged `partial_match`. Matching ignores accents and British/American spelling (`tumour`/`tumor`, `optimisation`/`optimization`) while keeping the original spelling, expands common abbreviations (`LLM`, `ML`, `RL`, `GNN`, `CNN`, `MRI`, `CT`) and recognizes listed variants (`Nasca`/`Nazca`, `Herculaneum`/`Ercolano`). Add new variants to `synonymGroups` in `worker.js`. A DOI in the query is matched against each record's source and paper links. The field filter accepts a field name or part of one (`bio`, `materials science`). Organization filters keep every word. Title matches rank first. Look up a discovery by the ID returned by search to get its original source and full evidence notes. Tool results are returned both as JSON text and as structured content.

The Worker keeps the parsed, indexed catalog for up to 10 minutes per warm isolate; concurrent requests share one download, and a failed refresh keeps serving the previous copy. It is stateless: only `POST /mcp` is accepted (`GET` and `DELETE` return 405). Each client IP is limited to 300 requests per minute through the Workers rate-limiting binding in `wrangler.toml`.

From this directory, use Node.js 22.12 or later (Wrangler refuses older versions).

```sh
npm ci
npm test
npm run dev
```

With a Cloudflare account authorized for the project's zone and using Workers Free, run `npm run deploy` to deploy the Worker and its custom subdomain. The Worker has no storage bindings, model calls or paid feature dependencies.

## MCP Registry listing

`server.json` describes this remote server for the official MCP Registry (namespace `io.github.marcello-pichini`, verified through GitHub sign-in). Bump `version` when the Worker changes, then publish from this directory:

```sh
mcp-publisher login github
mcp-publisher publish
```
