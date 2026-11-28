import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from harvest import known


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
