import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from harvest import known


class VulnerabilityIdentityRegressionTest(unittest.TestCase):
    def test_related_mentions_are_not_catalog_identities(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "data/vulnerabilities.json"
            data.parent.mkdir()
            data.write_text(json.dumps([{
                "id": "cve-2026-92745", "cves": ["CVE-2026-92745"],
                "summary": "Separate from CVE-2026-92747 and GHSA-aaaa-bbbb-cccc.",
                "advisory_url": "https://github.com/example/project/security/advisories/GHSA-1111-2222-3333",
                "source_url": "https://example.org/CVE-2026-92745?related=CVE-2026-94185",
            }, {"id": "ghsa-4444-5555-6666", "cves": []}]))
            index = known.Known(d)
            for ident in ("CVE-2026-92745", "GHSA-1111-2222-3333", "GHSA-4444-5555-6666"):
                self.assertTrue(index.vuln(ident), ident)
            for ident in ("CVE-2026-92747", "GHSA-aaaa-bbbb-cccc", "CVE-2026-94185"):
                self.assertFalse(index.vuln(ident), ident)

    def test_osv_debian_wrapper_matches_catalogued_and_excluded_cves(self):
        from harvest import vuln
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "data/vulnerabilities.json"
            data.parent.mkdir()
            data.write_text(json.dumps([{"id": "cve-2026-92745", "cves": ["CVE-2026-92745"]}]))
            exclusions = Path(d) / "research/vulnerability-exclusions.json"
            exclusions.parent.mkdir()
            exclusions.write_text(json.dumps([{"case_key": "CVE-2026-12345"}, {"case_key": "OSEC-2026-1"}, {"case_key": "local-case-42"}]))
            index = known.Known(d)
            self.assertTrue(index.vuln("OSEC-2026-1"))
            self.assertTrue(index.vuln("local-case-42"))
            for ident, expected in (("DEBIAN-CVE-2026-92745", True), ("DEBIAN-CVE-2026-12345", True), ("DEBIAN-CVE-2026-92747", False)):
                lead = vuln.osv_entry({"id": ident, "summary": "AI-assisted discovery", "aliases": []})
                self.assertEqual(index.vuln(*lead["ids"]), expected, ident)

class PaperIdentityRegressionTest(unittest.TestCase):
    def test_secondary_evidence_is_not_a_primary_paper_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            (root / "research").mkdir()
            (root / "data/discoveries.json").write_text(json.dumps([{
                "title": "Primary experiment",
                "source_url": "https://doi.org/10.1021/acsomega.4c07994",
                "paper_url": "https://arxiv.org/abs/2401.12345v2",
                "summary": "A different study is 10.1234/secondary and arXiv:2301.12345.",
                "evidence": {"evidence_urls": ["https://doi.org/10.4155/fmc-2023-0074", "https://arxiv.org/abs/2302.12345"]},
                "relationships": [{"url": "https://doi.org/10.1234/related"}],
            }]))
            (root / "data/archived-discoveries.json").write_text(json.dumps([{
                "title": "Archived primary experiment",
                "source_url": "https://doi.org/10.1234/archived",
                "paper_url": "https://arxiv.org/pdf/2201.12345.pdf",
            }]))
            (root / "research/discovery-exclusions.json").write_text(json.dumps([{"case_key": "10.1234/excluded"}]))
            index = known.Known(root)
            for doi in ("10.1021/acsomega.4c07994", "10.1234/archived", "10.1234/excluded"):
                with self.subTest(primary_doi=doi):
                    self.assertTrue(index.paper(doi=doi))
            for arxiv in ("2401.12345", "2201.12345"):
                with self.subTest(primary_arxiv=arxiv):
                    self.assertTrue(index.paper(arxiv=arxiv))
            for doi in ("10.1234/secondary", "10.4155/fmc-2023-0074", "10.1234/related"):
                with self.subTest(secondary_doi=doi):
                    self.assertFalse(index.paper(doi=doi))
            for arxiv in ("2301.12345", "2302.12345"):
                with self.subTest(secondary_arxiv=arxiv):
                    self.assertFalse(index.paper(arxiv=arxiv))


if __name__ == "__main__":
    unittest.main()
