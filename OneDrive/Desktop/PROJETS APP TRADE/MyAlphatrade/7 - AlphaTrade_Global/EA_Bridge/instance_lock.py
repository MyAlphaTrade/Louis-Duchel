"""
Instance lock — prevents two bridge processes from both actively managing
the SAME MT5 account at once.

Real incident (2026-08-07, caught during Phase 6 verification, no losses):
a second alphatg_bridge.py process, started manually for testing, connected
successfully to the SAME MT5 account already driven by the installed app's
own bridge (PID already running). A different BRIDGE_PORT does NOT prevent
this — MT5's Python API attaches to the one running MT5 terminal regardless
of which port the Flask process itself binds to, so two independent
processes can each get a live, working connection to the same account at
the same time. Nothing stopped in the code that could have had both
Position Manager loops (or two autonomous execution paths) fight over the
same open positions — the same root-cause family as the duplicate-orders
bug (Task #78, already fixed once for a different trigger).

Design: a heartbeat lease, not a PID-liveness check — no extra dependency
(no psutil), and self-heals if a bridge crashes without cleaning up: the
lock is only considered "held" while its last heartbeat is fresher than
LOCK_STALE_SECONDS. A process that can't acquire the lock for the account
it just connected to must not start position management or accept any
order-mutating request — see alphatg_bridge.py's use of this module.
"""
import json
import os
import time
from datetime import datetime, timezone

LOCK_FILENAME = "bridge_instance.lock"
# Position Manager heartbeats every ~5s while holding the lock (see
# alphatg_bridge.py) — 3 missed beats is a safe margin above normal
# scheduling jitter without leaving a crashed process's lock stuck for long.
LOCK_STALE_SECONDS = 15


def _lock_path(db_dir):
    return os.path.join(db_dir, LOCK_FILENAME)


def _read(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write(path, login):
    payload = {
        "pid": os.getpid(),
        "login": login,
        "heartbeat_ts": time.time(),
        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)  # atomic on the same filesystem — no torn reads


def acquire_or_check(db_dir, login):
    """Call once, right after a successful MT5 connection, before starting
    the Position Manager. Returns (acquired: bool, holder: dict|None).

    acquired=True: this process now owns the lock for `login` (the lock was
    free, stale, or already owned by this exact process) — safe to start
    managing positions and to accept order-mutating requests.
    acquired=False: a DIFFERENT, live process already holds the lock for
    this SAME login — `holder` describes it (pid/login/heartbeat_at). This
    process must not start the Position Manager and must refuse order
    writes until the situation is resolved (the other bridge stopped, or
    this one is the wrong one to be running).
    """
    path = _lock_path(db_dir)
    holder = _read(path)

    if holder:
        is_fresh = (time.time() - holder.get("heartbeat_ts", 0)) < LOCK_STALE_SECONDS
        is_other_process = holder.get("pid") != os.getpid()
        is_same_login = holder.get("login") == login
        if is_fresh and is_other_process and is_same_login:
            return False, holder

    _write(path, login)
    return True, None


def heartbeat(db_dir, login):
    """Call periodically (from the Position Manager loop) to keep this
    process's ownership of the lock fresh, so a crashed process's lock
    goes stale quickly instead of blocking a legitimate restart forever."""
    _write(_lock_path(db_dir), login)


def is_held_by_this_process(db_dir, login):
    """True if this process currently owns a fresh lock for `login`. Used
    to gate order-mutating endpoints against a bridge that lost the race
    at startup (or whose lock went stale mid-run some other way)."""
    holder = _read(_lock_path(db_dir))
    if not holder:
        return False
    is_fresh = (time.time() - holder.get("heartbeat_ts", 0)) < LOCK_STALE_SECONDS
    return is_fresh and holder.get("pid") == os.getpid() and holder.get("login") == login
