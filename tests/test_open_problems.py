import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import open_problems as op


def solved(outcome, pr='https://github.com/a/b/pull/1'):
    return {'problem_id': 'P' + outcome, 'title': 'T', 'outcome': outcome, 'polarity': 'proof',
            'created_at': '2026-11-28T10:00:00Z', 'handle': 'h', 'agent': 'a', 'model': 'm', 'pr_url': pr}


class OpenProblemsTest(unittest.TestCase):
    def test_build_data_keeps_results_drops_steps_and_appends_history(self):
        lts = {'byOutcome': {'open': 1, 'step': 1}, 'solved': [solved('open'), solved('step'), solved('known', 'javascript:x')]}
        stats = {'catalog': {'open': 5, 'unformalized': 7}}
        head = {'counters': {'lemmas': 3, 'checked': 2, 'refuted': 1, 'conjecture': 0, 'in_work': 0, 'agent_sessions_total': 9},
                'started_at': '2026-11-22T00:00:00Z'}
        prev = {'history': [{'date': '2026-11-27'}, {'date': '2026-11-28'}]}
        d = op.build_data(lts, stats, head, {'programs': []}, {'papers': []}, prev, '2026-11-28T12:00Z')
        self.assertEqual([r['outcome'] for r in d['results']], ['open', 'known'])
        self.assertIsNone(d['results'][1]['pr'])
        self.assertEqual([h['date'] for h in d['history']], ['2026-11-27', '2026-11-28'])
        self.assertEqual(d['history'][-1]['lefttosolve']['open_problems'], 5)

    def test_generated_page_matches_data(self):
        page = (op.ROOT / 'open-problems.html').read_text()
        self.assertIn('<title>' + op.TITLE + '</title>', page)
        self.assertIn('href="https://aisciencetracker.org/open-problems.html"', page)


if __name__ == '__main__':
    unittest.main()
