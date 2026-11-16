import contextlib
import functools
import http.server
import importlib.util
import io
import os
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/ai-science-tracker/skills/ai-science-tracker/scripts/tracker.py"


class TrackerSkillTest(unittest.TestCase):
    """Runs the plugin's query script against the local data files."""

    @classmethod
    def setUpClass(cls):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        handler.log_message = lambda *a: None
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        os.environ["AI_SCIENCE_TRACKER_BASE"] = f"http://127.0.0.1:{cls.server.server_port}"
        spec = importlib.util.spec_from_file_location("tracker", SCRIPT)
        cls.tracker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tracker)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        os.environ.pop("AI_SCIENCE_TRACKER_BASE", None)

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.tracker.main(list(args))
        return code, out.getvalue()

    def test_search_finds_vulnerability_by_cve(self):
        code, out = self.run_cli("search", "CVE-2025-37899", "--collection", "vulnerabilities")
        self.assertEqual(code, 0)
        self.assertIn("security.html#cve-2025-37899", out)

    def test_new_filters_by_date_for_every_collection(self):
        code, out = self.run_cli("new", "--since", "2999-01-01")
        self.assertEqual(code, 0)
        for name in ("discoveries", "models", "vulnerabilities"):
            self.assertIn(f"## {name}: 0 since 2999-01-01", out)

    def test_get_returns_record_or_error(self):
        self.assertEqual(self.run_cli("get", "cve-2025-37899")[0], 0)
        self.assertEqual(self.run_cli("get", "no-such-id")[0], 1)


if __name__ == "__main__":
    unittest.main()
