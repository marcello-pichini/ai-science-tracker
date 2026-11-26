# Security policy

AI Science Tracker is a static website, a read-only public dataset and a read-only MCP server (`https://mcp.aisciencetracker.org/mcp`). None of them hold accounts, credentials or personal data.

## Reporting a vulnerability

Report security issues privately through GitHub's [private vulnerability reporting](https://github.com/marcello-pichini/ai-science-tracker/security/advisories/new) for this repository. Please do not open a public issue for an unpatched problem. Include the affected URL or file, the steps to reproduce and the impact you observed.

You can expect an acknowledgement within 7 days. Fixes are deployed from the `main` branch; there are no separately supported release lines.

## Scope

In scope: the site and its generated pages, the static API, the MCP server under `mcp/`, the plugin packages under `plugins/`, and the scripts under `scripts/`.

Out of scope: the third-party sources linked from catalog entries, and the vulnerability cases the catalog describes. Those belong to their own vendors.
