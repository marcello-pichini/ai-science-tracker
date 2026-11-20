import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deployment_state', ROOT / 'scripts/deployment_state.py')
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


class PipelineTests(unittest.TestCase):
    def fetch(self, path):
        if '/commits/' in path:
            return {'sha': 'new', 'commit': {'committer': {'date': '2026-11-18T00:00:00Z'}}}
        if '/statuses' in path:
            return [{'state': 'success'}]
        if '/actions/' in path:
            return {'workflow_runs': [{'head_sha': self.sha, 'head_branch': 'main', 'event': 'push', 'head_repository': {'full_name': 'owner/repo'}, 'conclusion': self.conclusion}]}
        return [{'sha': self.sha, 'id': 1}]

    def test_current_verified_deployment(self):
        self.sha, self.conclusion = 'new', 'success'
        self.assertEqual(state.select('owner/repo', True, True, self.fetch)['deployed_sha'], 'new')

    def test_failed_check_blocks_publisher(self):
        self.sha, self.conclusion = 'new', 'failure'
        with self.assertRaises(RuntimeError):
            state.select('owner/repo', True, True, self.fetch)

    def test_old_deployment_retained_for_monitor_but_blocks_publisher(self):
        self.sha, self.conclusion = 'old', 'success'
        self.assertEqual(state.select('owner/repo', fetch=self.fetch)['expected_sha'], 'new')
        with self.assertRaises(RuntimeError):
            state.select('owner/repo', True, True, self.fetch)

    def test_source_failure_restores_output_then_other_source_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a').write_text('old')
            bad = [sys.executable, '-c', "from pathlib import Path; Path('a').write_text('broken'); raise SystemExit(1)"]
            self.assertEqual(state.source_transaction(root, 'a', ['a'], bad)['status'], 'held')
            self.assertEqual((root / 'a').read_text(), 'old')
            good = [sys.executable, '-c', "from pathlib import Path; Path('b').write_text('new')"]
            self.assertEqual(state.source_transaction(root, 'b', ['b'], good)['status'], 'updated')

    def test_refresh_failed_download_does_not_block_later_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data/benchmarks').mkdir(parents=True)
            (root / 'scripts').mkdir()
            (root / 'scripts/public-benchmark-inputs.json').write_text('{}')
            for filename in ('models.json', 'model-progress.json', 'swe-bench.json'):
                (root / 'data' / filename).write_text('{}')
            def run(command, **kwargs):
                if command[0] == 'curl':
                    if 'notable_ai_models.csv' in command[-1]:
                        return subprocess.CompletedProcess(command, 22)
                    Path(command[command.index('-o') + 1]).write_text('download')
                return subprocess.CompletedProcess(command, 0)
            with patch.object(state.subprocess, 'run', side_effect=run):
                state.refresh(root)
            report = __import__('json').loads((root / 'work/source-refresh-report.json').read_text())
            self.assertFalse(report['complete'])
            self.assertEqual([r['status'] for r in report['sources']], ['held', 'unchanged', 'unchanged', 'unchanged'])
            self.assertEqual((root / 'data/models.json').read_text(), '{}')

    def test_refresh_passes_unchanged_epoch_zip_to_progress_when_catalog_changes(self):
        for failure in (None, 'download', 'import'):
            with self.subTest(failure=failure):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / 'data/benchmarks').mkdir(parents=True)
                    (root / 'scripts').mkdir()
                    (root / 'scripts/public-benchmark-inputs.json').write_text('{}')
                    models_path = root / 'data/models.json'
                    models_path.write_text(json.dumps({'source': {'csv_sha256': 'old'}}))
                    progress_path = root / 'data/model-progress.json'
                    progress = {'zip_sha256': hashlib.sha256(b'download').hexdigest(), 'catalog_snapshot': 'old'}
                    progress_path.write_text(json.dumps(progress))
                    (root / 'data/swe-bench.json').write_text('{}')

                    def run(command, **kwargs):
                        if command[0] == 'curl':
                            if failure == 'download' and command[-1].endswith('/benchmark_data.zip'):
                                return subprocess.CompletedProcess(command, 22)
                            Path(command[command.index('-o') + 1]).write_bytes(b'download')
                        elif command[1] == 'scripts/generate_models.py':
                            models_path.write_text(json.dumps({'source': {'csv_sha256': 'new'}}))
                        elif command[1] == 'scripts/import_model_progress.py':
                            self.assertIn('--refresh-if-changed', command)
                            progress['catalog_snapshot'] = json.loads(models_path.read_text())['source']['csv_sha256']
                            progress_path.write_text(json.dumps(progress))
                            if failure == 'import':
                                raise subprocess.CalledProcessError(1, command)
                        return subprocess.CompletedProcess(command, 0)

                    with patch.object(state.subprocess, 'run', side_effect=run):
                        state.refresh(root)
                    report = json.loads((root / 'work/source-refresh-report.json').read_text())
                    statuses = [r['status'] for r in report['sources']]
                    expected = 'old' if failure else 'new'
                    self.assertEqual(statuses, ['held', 'held', 'unchanged', 'unchanged'] if failure
                                     else ['updated', 'updated', 'unchanged', 'unchanged'])
                    self.assertEqual(json.loads(models_path.read_text())['source']['csv_sha256'], expected)
                    self.assertEqual(json.loads(progress_path.read_text())['catalog_snapshot'], expected)

    def test_public_artifact_retains_license_documents(self):
        workflow = (ROOT / '.github/workflows/check.yml').read_text()
        block = workflow.split('      - name: Package tracked public snapshot\n        run: |\n')[1].split('      - uses:')[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            for path in ('index.html', 'docs/public-benchmarks.md', 'docs/benchmark-licenses/license.txt', '.github/workflows/check.yml', 'scripts/private.py', 'tests/test_x.py'):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('public fixture')
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-qm', 'fixture'], cwd=root, check=True)
            env = dict(__import__('os').environ, RUNNER_TEMP=str(root / 'runner'))
            subprocess.run(['bash', '-e', '-c', block], cwd=root, env=env, check=True)
            self.assertTrue((root / 'runner/site/docs/public-benchmarks.md').is_file())
            self.assertTrue((root / 'runner/site/docs/benchmark-licenses/license.txt').is_file())
            self.assertFalse((root / 'runner/site/.github').exists())

    def test_refresh_stages_new_generated_files_without_private_inputs(self):
        workflow = (ROOT / '.github/workflows/daily-refresh.yml').read_text()
        stage = next(line.strip() for line in workflow.splitlines() if line.strip().startswith('git add '))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            paths = [
                'index.html', 'profile.html', 'models.html', 'search.html', 'security.html',
                'model-progress.html', 'methodology.html', 'dataset.html',
                'it/index.html', 'de/index.html', 'fr/index.html', 'es/index.html',
                'data/new.json', 'scripts/public-benchmark-inputs.json', 'share/new.html',
                'profiles/new.html', 'og/new.png', 'api/new.json', 'feed.xml', 'llms.txt',
                'sitemap.xml', 'robots.txt', 'work/private.csv',
            ]
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('fixture')
            subprocess.run(['bash', '-e', '-c', stage], cwd=root, check=True)
            staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], cwd=root, text=True).splitlines()
            self.assertEqual(set(staged), set(paths) - {'work/private.csv'})

    def test_workflow_gates_and_explicit_bot_dispatch(self):
        check = (ROOT / '.github/workflows/check.yml').read_text()
        self.assertIn('needs: check', check)
        self.assertIn('actions/deploy-pages@v4', check)
        self.assertIn('git ls-remote origin refs/heads/main', check)
        daily = (ROOT / '.github/workflows/daily-refresh.yml').read_text()
        self.assertIn('gh workflow run check.yml --ref main -f expected_sha=', daily)
        self.assertNotIn('git add -A', daily)
        publisher = (ROOT / '.github/workflows/weekly-release.yml').read_text()
        self.assertIn('--require-check --require-current', publisher)
        self.assertIn("github.event.workflow_run.event != 'pull_request'", publisher)
        self.assertIn('--deployment-metadata', (ROOT / '.github/workflows/site-monitor.yml').read_text())
