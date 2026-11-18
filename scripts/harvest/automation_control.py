"""Private research-run exclusion and bounded follow-up scheduling."""
import argparse
import ctypes
import sys
from datetime import date, datetime, timedelta, timezone
import json
from contextlib import contextmanager
import fcntl
import os
import socket
import tempfile
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = ROOT / "research" / "automation-control" / "run.lock"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def guarded(path):
    """Keep the guard inode permanently; serialize every read/modify operation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".guard").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield path


def process_identity(pid):
    """Return a stable local process start identity; unknown must fail closed."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError("owner PID must be a positive integer")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    # Linux start ticks are scoped by boot ID, so PID reuse/reboot is distinguishable.
    if Path("/proc/sys/kernel/random/boot_id").exists():
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            return f"linux:{boot}:{fields[19]}"
        except FileNotFoundError:
            return None
    if sys.platform == "darwin":
        # PROC_PIDTBSDINFO exposes kernel start seconds/microseconds without a ps child.
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        probe = library.proc_pidinfo
        probe.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                          ctypes.c_void_p, ctypes.c_int]
        probe.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(136)
        count = probe(pid, 3, 0, buffer, len(buffer))
        if count != len(buffer):
            raise OSError(ctypes.get_errno(), "Cannot inspect execution supervisor")
        seconds = int.from_bytes(buffer.raw[120:128], sys.byteorder)
        microseconds = int.from_bytes(buffer.raw[128:136], sys.byteorder)
        return f"darwin:{seconds}:{microseconds}"
    raise ValueError("Process identity is supported only on Linux and macOS")


def write_owner(owner, path):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(owner, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def acquire(run_id, path=DEFAULT_LOCK, owner_pid=None):
    """Register only an explicitly supplied execution supervisor, never this CLI PID.

    The supervisor must span the entire job. Without one, exclusion works but
    dead-owner recovery intentionally remains unavailable.
    """
    with guarded(path) as path:
        if path.exists():
            raise FileExistsError("Run lock already exists")
        owner = {"run_id": run_id, "token": uuid.uuid4().hex, "started_at": utc_now(),
                 "host": socket.gethostname()}
        owner["heartbeat_at"] = owner["started_at"]
        if owner_pid is not None:
            identity = process_identity(owner_pid)
            if identity is None:
                raise ValueError("Execution supervisor is already dead")
            owner.update(owner_pid=owner_pid, owner_start=identity)
        write_owner(owner, path)
        return owner


def _read_owner(token, path):
    owner = json.loads(path.read_text())
    if owner.get("token") != token:
        raise PermissionError("Run lock belongs to another execution")
    return owner


def read_owner(token, path=DEFAULT_LOCK):
    with guarded(path) as path:
        return _read_owner(token, path)


def heartbeat(token, path=DEFAULT_LOCK):
    with guarded(path) as path:
        owner = _read_owner(token, path)
        owner["heartbeat_at"] = utc_now()
        write_owner(owner, path)
        return owner


def release(token, path=DEFAULT_LOCK):
    with guarded(path) as path:
        _read_owner(token, path)
        path.unlink()


def liveness(owner):
    if owner.get("host") != socket.gethostname() or not owner.get("owner_start"):
        return "unknown"
    try:
        current = process_identity(owner.get("owner_pid"))
    except (OSError, ValueError):
        return "unknown"
    return "alive" if current == owner["owner_start"] else "dead"


def status(path=DEFAULT_LOCK):
    with guarded(path) as path:
        if not path.exists():
            return {"locked": False}
        owner = json.loads(path.read_text())
        return dict(owner, locked=True, owner_liveness=liveness(owner))


def recover(token, path=DEFAULT_LOCK, stale_seconds=300):
    """Remove only the expected stale lock with a provably dead local supervisor."""
    if stale_seconds < 0:
        raise ValueError("stale seconds must be nonnegative")
    with guarded(path) as path:
        owner = _read_owner(token, path)
        if liveness(owner) != "dead":
            raise PermissionError("Recovery requires a provably dead local supervisor")
        heartbeat_at = datetime.fromisoformat(owner["heartbeat_at"])
        if heartbeat_at.tzinfo is None:
            raise ValueError("Heartbeat must include a timezone")
        age = (datetime.now(timezone.utc) - heartbeat_at).total_seconds()
        if age < stale_seconds:
            raise PermissionError("Dead owner lock is not yet stale")
        path.unlink()
        return {"recovered": True, "previous_run_id": owner["run_id"]}


def hold_plan(attempts, checked_on, priority="normal"):
    """Call after a real evidence attempt; elapsed time never rejects a case."""
    if attempts < 1:
        raise ValueError("attempts must include at least one completed check")
    if priority not in ("high", "normal", "low"):
        raise ValueError("invalid priority")
    checked = date.fromisoformat(checked_on)
    delays = (1, 3, 7, 14, 30)
    delay = delays[min(attempts - 1, len(delays) - 1)]
    return {"attempts": attempts, "last_checked_on": checked.isoformat(),
            "next_check_on": (checked + timedelta(days=delay)).isoformat(),
            "priority": priority, "retry_after_days": delay}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("acquire")
    start.add_argument("--run-id", required=True)
    start.add_argument("--owner-pid", type=int, help="Long-lived execution supervisor PID; never the short-lived CLI PID")
    for command in ("heartbeat", "release", "recover"):
        child = commands.add_parser(command)
        child.add_argument("--token", required=True)
        if command == "recover":
            child.add_argument("--stale-seconds", type=int, default=300)
    commands.add_parser("status")
    plan = commands.add_parser("plan")
    plan.add_argument("--attempts", type=int, required=True)
    plan.add_argument("--checked-on", required=True)
    plan.add_argument("--priority", default="normal")
    args = parser.parse_args(argv)
    try:
        if args.command == "acquire":
            result = acquire(args.run_id, args.lock_path, args.owner_pid)
        elif args.command == "heartbeat":
            result = heartbeat(args.token, args.lock_path)
        elif args.command == "release":
            release(args.token, args.lock_path)
            result = {"released": True}
        elif args.command == "recover":
            result = recover(args.token, args.lock_path, args.stale_seconds)
        elif args.command == "status":
            result = status(args.lock_path)
        else:
            result = hold_plan(args.attempts, args.checked_on, args.priority)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
