import importlib.util
import json
import os
import subprocess
import sys
from unittest import mock
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/harvest/automation_control.py"
spec = importlib.util.spec_from_file_location("automation_control", SCRIPT)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class AutomationControlTest(unittest.TestCase):
    def test_overlap_cannot_replace_owner_and_release_allows_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            first = control.acquire("first", path)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                control.acquire("overlap", path)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(PermissionError):
                control.release("wrong-token", path)
            self.assertEqual(control.heartbeat(first["token"], path)["run_id"], "first")
            control.release(first["token"], path)
            self.assertEqual(control.acquire("next", path)["run_id"], "next")

    def test_abandoned_or_incomplete_lock_is_never_automatically_stolen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            path.write_text("")
            with self.assertRaises(FileExistsError):
                control.acquire("other", path)
            self.assertEqual(path.read_text(), "")

    def test_live_and_unknown_owners_are_never_recovered_by_age(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            for pid in (None, os.getpid()):
                owner = control.acquire("owner", path, owner_pid=pid)
                owner["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
                path.write_text(json.dumps(owner))
                with self.assertRaises(PermissionError):
                    control.recover(owner["token"], path, stale_seconds=0)
                self.assertEqual(control.status(path)["owner_liveness"],
                                 "unknown" if pid is None else "alive")
                control.release(owner["token"], path)

    def test_real_dead_supervisor_recovery_and_old_token_fencing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                owner = control.acquire("crashing-run", path, owner_pid=child.pid)
                child.terminate()
                child.wait(timeout=3)
                self.assertEqual(control.status(path)["owner_liveness"], "dead")
                with self.assertRaises(PermissionError):
                    control.recover(owner["token"], path)
                self.assertTrue(control.recover(owner["token"], path, 0)["recovered"])
                successor = control.acquire("successor", path)
                for operation in (control.heartbeat, control.release, control.recover):
                    with self.assertRaises(PermissionError):
                        operation(owner["token"], path)
                self.assertEqual(control.status(path)["token"], successor["token"])
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=3)

    def test_pid_reuse_is_dead_but_foreign_host_and_probe_failure_are_unknown(self):
        owner = {"host": control.socket.gethostname(), "owner_pid": os.getpid(),
                 "owner_start": "previous-process"}
        self.assertEqual(control.liveness(owner), "dead")
        with mock.patch.object(control, "process_identity", side_effect=PermissionError):
            self.assertEqual(control.liveness(owner), "unknown")
        owner["host"] = "different-host"
        self.assertEqual(control.liveness(owner), "unknown")

    def test_competing_cli_processes_have_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            commands = [[sys.executable, str(SCRIPT), "--lock-path", str(path),
                         "acquire", "--run-id", str(n)] for n in range(8)]
            children = [subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
                        for command in commands]
            outputs = [json.loads(child.communicate(timeout=5)[0]) for child in children]
            self.assertEqual(sum(child.returncode == 0 for child in children), 1)
            winner = next(value for value in outputs if "token" in value)
            self.assertEqual(control.status(path)["token"], winner["token"])

    def test_failed_atomic_heartbeat_preserves_previous_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            owner = control.acquire("owner", path)
            original = path.read_bytes()
            with mock.patch.object(control.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    control.heartbeat(owner["token"], path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(set(Path(directory).iterdir()),
                             {path, path.with_name("run.lock.guard")})

    def test_backoff_caps_delay_without_expiring_the_case(self):
        self.assertEqual([control.hold_plan(n, "2026-11-18")["retry_after_days"]
                          for n in (1, 2, 3, 4, 5, 100)], [1, 3, 7, 14, 30, 30])
        self.assertEqual(control.hold_plan(1, "2026-12-31")["next_check_on"], "2027-01-01")
        with self.assertRaises(ValueError):
            control.hold_plan(0, "2026-11-18")


if __name__ == "__main__":
    unittest.main()
