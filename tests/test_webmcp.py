"""WebMCP tools must stay inert without browser support and answer from the public catalog files."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WebMcpTests(unittest.TestCase):
    def test_tools_register_only_with_model_context_and_search_records(self):
        result = subprocess.run(['node', '-e', """
const assert = require('node:assert/strict');
globalThis.location = {origin: 'https://example.org'};
require('./assets/webmcp.js');  // no modelContext: must not throw or register anything
delete require.cache[require.resolve('./assets/webmcp.js')];
const tools = {};
globalThis.document = {modelContext: {registerTool: t => { tools[t.name] = t; }}};
const discoveries = [
  {id: 'a', title: 'Antibiotic design', summary: 'x', field: 'biology', publication_date: '2025-08-14',
   paper_url: 'https://doi.org/10.1234/abc', source_url: 'https://example.org/a'},
  {id: 'b', title: 'Protein folding', summary: 'antibiotic mentioned', field: 'biology', publication_date: '2020-11-30'}];
const vulns = [{id: 'CVE-2026-1111', title: 'Flaw', products: ['acme:lib'], classes: ['SQL injection']}];
globalThis.fetch = async url => new Response(JSON.stringify(String(url).includes('vulnerabilities') ? vulns : discoveries));
require('./assets/webmcp.js');
(async () => {
  assert.deepEqual(Object.keys(tools).sort(), ['get_discovery', 'search_discoveries', 'search_vulnerabilities']);
  assert.ok(Object.values(tools).every(t => t.annotations.readOnlyHint));
  const hits = await tools.search_discoveries.execute({query: 'antibiotic'});
  assert.deepEqual(hits.results.map(r => r.id), ['a', 'b']);
  assert.equal(hits.results[0].catalog_url, 'https://example.org/share/a.html');
  assert.deepEqual((await tools.search_discoveries.execute({query: 'antibiotic', year: 2020})).results.map(r => r.id), ['b']);
  assert.deepEqual((await tools.search_discoveries.execute({query: '10.1234/abc'})).results.map(r => r.id), ['a']);
  assert.equal((await tools.search_vulnerabilities.execute({query: 'cve-2026-1111'})).total, 1);
  assert.equal((await tools.search_vulnerabilities.execute({query: 'sql injection lib'})).results[0].catalog_url, 'https://example.org/security.html?q=CVE-2026-1111');
})().catch(e => { console.error(e); process.exit(1); });
"""], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
