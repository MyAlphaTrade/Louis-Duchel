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

Real incident (2026-08-19, no losses, but ~50 real minutes of blocked
trading): the self-healing above only works if something actually RETRIES
acquire_or_check() later. The original alphatg_bridge.py called it exactly
once, at connect time, and cached the result for the process's whole
lifetime — a heartbeat() call and a read-only is_held_by_this_process()
check filled in afterward. A routine app restart landed inside the ~15s
window where the just-killed process's last heartbeat still looked fresh:
the new process was correctly denied the lock at that instant, but then
never asked again — Position Manager never started and every order was
refused with DUPLICATE_BRIDGE for the rest of that run, long after the
old process (and its stale lock) were gone. Fixed by having every caller
(the Position Manager loop, every cycle, and the order-mutating guard, on
every request) call acquire_or_check() itself instead of a separate
heartbeat/read-only check — it's a no-op refresh when already held, so
this is also, transparently, a retry. heartbeat() and
is_held_by_this_process() were removed as this module's only 2026-08-07
callers switched to acquire_or_check(); reintroduce a heartbeat-only path
only if a future caller genuinely needs "refresh without ever retrying".
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
    """Call right after a successful MT5 connection, before starting the
    Position Manager — AND call again on every later attempt to manage
    positions or mutate an order. Cheap (one small file read + maybe one
    atomic write), safe to call as often as needed: a no-op refresh when
    this process already holds the lock, a real (re-)acquisition attempt
    otherwise. Calling it only once at startup is what caused the real
    2026-08-19 incident documented in this module's docstring — always
    call it again rather than caching the result past a single check.
    Returns (acquired: bool, holder: dict|None).

    acquired=True: this process now owns the lock for `login` (the lock was
    free, stale, or already owned by this exact process) — safe to manage
    positions and to accept order-mutating requests right now.
    acquired=False: a DIFFERENT, live process currently holds the lock for
    this SAME login — `holder` describes it (pid/login/heartbeat_at). This
    process must not manage positions or accept order writes THIS time;
    call again next cycle rather than remembering this result.
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
