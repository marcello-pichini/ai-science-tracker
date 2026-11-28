"""Offline interruption, replay, source isolation and pagination regressions."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from harvest import disc, state, run_disc


def row(key):
    return disc.lead('test', key, [], '2026-11-01', key, '', 0)


class IncrementalTest(unittest.TestCase):
    def test_failure_preserves_partial_and_isolates_sources(self):
        def bad(report, checkpoint, budget=None):
            yield row('partial')
            raise RuntimeError('blocked')
        def good(report, checkpoint, budget=None):
            yield row('good')
            report['status'] = 'complete'
        with tempfile.TemporaryDirectory() as directory:
            out, cp = Path(directory) / 'leads.jsonl', Path(directory) / 'state.json'
            rows, report = state.collect_sources({'bad': bad, 'good': good}, {'from': 'a', 'to': 'b'}, out, cp)
            self.assertEqual({r['key'] for r in rows}, {'partial', 'good'})
            self.assertEqual(report['status'], 'incomplete')
            self.assertNotIn('completed_window', report['sources']['bad'])
            self.assertEqual(report['sources']['good']['status'], 'complete')
            self.assertTrue(Path(str(out) + '.coverage.json').exists())

    def test_cli_failure_nonzero_and_resume_duplicate_safe(self):
        calls = []
        fail = [True]
        def adapter(start, end, min_score, report, checkpoint, budget=None):
            calls.append(report.get('cursor', 0))
            for offset in range(report.get('cursor', 0), 3):
                yield row(str(offset))
                if offset == 1 and fail[0]:
                    raise RuntimeError('interrupted before cursor commit')
                report['cursor'] = offset + 1
                checkpoint()
            report['status'] = 'complete'
        with tempfile.TemporaryDirectory() as directory, patch.dict(disc.ADAPTERS, {'mock': adapter}):
            out, cp = Path(directory) / 'l.jsonl', Path(directory) / 'c.json'
            args = ['--from', '2026-11-01', '--to', '2026-11-02', '--sources', 'mock', '--out', str(out), '--checkpoint', str(cp)]
            self.assertEqual(run_disc.main(args), 1)
            self.assertEqual(len(out.read_text().splitlines()), 2)
            fail[0] = False
            self.assertEqual(run_disc.main(args), 0)
            self.assertEqual(calls, [0, 1])
            self.assertEqual(len(out.read_text().splitlines()), 3)

    def test_openalex_exceeds_old_cap_and_explicit_budget_resumes(self):
        calls = []
        def response(url):
            from urllib.parse import urlparse, parse_qs
            page = int(parse_qs(urlparse(url).query)['page'][0])
            calls.append(page)
            return {'results': [{'id': f'{page}-{i}', 'title': 'ordinary result'} for i in range(100 if page <= 16 else 1)]}
        report = {}
        with patch.object(disc, 'OA_TERMS', ['AI']), patch.object(disc.fetch, 'get_json', side_effect=response):
            self.assertEqual(len(list(disc.openalex('a', 'b', report=report, budget=2))), 200)
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['cursor']['page'], 3)
            list(disc.openalex('a', 'b', report=report))
        self.assertEqual(calls, list(range(1, 18)))
        self.assertEqual(report['status'], 'complete')

    def test_europepmc_exceeds_old_page_cap(self):
        count = [0]
        def response(url):
            count[0] += 1
            return {'resultList': {'result': [{'id': str(count[0])}] if count[0] <= 12 else []}, 'nextCursorMark': str(count[0])}
        report = {}
        with patch.object(disc.fetch, 'get_json', side_effect=response):
            self.assertEqual(len(list(disc.europepmc('a', 'b', report=report))), 12)
        self.assertEqual(count[0], 13)
        self.assertEqual(report['status'], 'complete')

    def test_arxiv_exceeds_old_record_cap(self):
        count = [0]
        def response(*args, **kwargs):
            count[0] += 1
            entries = ''.join(f'<entry><id>https://arxiv.org/abs/{count[0]}.{i}</id><title>x</title></entry>' for i in range(200 if count[0] < 5 else 0))
            return '<feed xmlns="http://www.w3.org/2005/Atom">' + entries + '</feed>'
        report = {}
        with patch.object(disc.fetch, 'get_text', side_effect=response), patch.object(disc.time, 'sleep'):
            self.assertEqual(len(list(disc.arxiv('2026-01-01', '2026-01-02', report=report))), 800)
        self.assertEqual(report['status'], 'complete')

    def test_portable_bundle_resumes_in_different_directory(self):
        import shutil
        seen = []
        def adapter(report, checkpoint, budget=None):
            offset = report.get('cursor', 0)
            seen.append(offset)
            yield row(str(offset))
            report['cursor'] = offset + 1
            checkpoint()
            report['status'] = 'incomplete' if offset == 0 else 'complete'
        with tempfile.TemporaryDirectory() as original, tempfile.TemporaryDirectory() as restored:
            out, cp = Path(original) / 'leads.jsonl', Path(original) / 'state.json'
            state.collect_sources({'mock': adapter}, {'from': 'a', 'to': 'b'}, out, cp)
            restored_out, restored_cp = Path(restored) / out.name, Path(restored) / cp.name
            shutil.copyfile(out, restored_out)
            shutil.copyfile(cp, restored_cp)
            rows, report = state.collect_sources({'mock': adapter}, {'from': 'a', 'to': 'b'}, restored_out, restored_cp)
            self.assertEqual(seen, [0, 1])
            self.assertEqual({r['key'] for r in rows}, {'0', '1'})
            self.assertEqual(report['status'], 'complete')

    def test_legacy_absolute_key_migrates_and_missing_leads_blocks_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            out, cp = Path(directory) / 'leads.jsonl', Path(directory) / 'state.json'
            job = {'window': {'from': 'a'}, 'sources': {'mock': {'status': 'complete', 'retrieved': 1}}}
            state.save({'jobs': {str(out.resolve()): job}}, cp)
            with self.assertRaisesRegex(ValueError, 'restore both files'):
                state.collect_sources({'mock': lambda: []}, {'from': 'a'}, out, cp)
            state.write_leads([row('retained')], out)
            rows, _ = state.collect_sources({'mock': lambda: []}, {'from': 'a'}, out, cp)
            self.assertEqual(rows[0]['key'], 'retained')
            self.assertIn(state.job_key(out, ['mock']), state.load(cp)['jobs'])
            self.assertNotIn(str(out.resolve()), state.load(cp)['jobs'])
