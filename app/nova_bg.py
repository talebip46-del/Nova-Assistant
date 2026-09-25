#!/usr/bin/env python3
# =====================================================================
#  Nova Code - background task runner (v5.0)
#
#  Long jobs (builds, big test suites, data conversion) must not freeze
#  the prompt. /bg <cmd> starts a workspace shell command on a daemon
#  thread with capped output capture; the REPL keeps working and
#  announces the completion on the next prompt:
#
#      [bg] started #b003: npm run build      (check: /bg log b003)
#      ...
#      [bg] #b003 FINISHED (exit 0) - 42s - /bg log b003
#
#  State lives in .nova/bg/<id>.json + <id>.log (survives the process,
#  so a crashed session's finished jobs are reported on next start).
#  The web face polls the same state and can raise a PWA notification.
#
#  Guards: MAX_CONCURRENT running tasks, output cap per task, a stale
#  "running" entry whose process died is marked 'died' on inspection,
#  old logs are pruned. Pure standard library.
# =====================================================================
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:
    natom = None

from nova_policy import NOVA_DIR

# v6.3: security layer - command screening + audit trail. Optional like
# every helper: a missing file degrades to the old (unscreened) behavior
# instead of killing background tasks entirely.
try:
    import nova_security as nsec
except Exception:
    nsec = None
try:
    import nova_log
except Exception:
    nova_log = None

BG_SUB = "bg"
MAX_CONCURRENT = 4
MAX_OUTPUT = 200_000
MAX_LOG_LINES = 400
MAX_AGE_S = 48 * 3600        # prune finished logs after two days

_PROCS = {}                  # id -> Popen (this process only, for /bg kill)
# v6.5: RLock - start() holds it across id-allocation + first meta write
# and _next_id() re-acquires it (a plain Lock would self-deadlock there).
_LOCK = threading.RLock()


def bg_dir(ws):
    return Path(ws) / NOVA_DIR / BG_SUB


def _meta_path(ws, tid):
    return bg_dir(ws) / (tid + ".json")


def _log_path(ws, tid):
    return bg_dir(ws) / (tid + ".log")


def _next_id(ws):
    with _LOCK:
        n = 0
        try:
            for p in bg_dir(ws).glob("b*.json"):
                m = re.match(r"b(\d+)", p.name)
                if m:
                    n = max(n, int(m.group(1)))
        except OSError:
            pass
        # v6.2.1 fix: 3-digit padding overflowed at b999 - "b1000" then
        # sorted BEFORE "b999" (lexicographic newest-first). 4 digits out-
        # live any realistic single workspace.
        return f"b{n + 1:04d}"


def _write_meta(ws, meta):
    p = _meta_path(ws, meta["id"])
    # v6.7: unique scratch name (cross-process tmp collision)
    if natom is not None:
        natom.write_text_atomic(
            p, json.dumps(meta, ensure_ascii=False, indent=1))
        return
    # v8.0: the fallback no longer uses one fixed bXXXX.json.tmp name -
    # two concurrent writers truncating the same scratch file published
    # torn JSON (the exact bug nova_atomic exists to prevent).
    tmp = p.with_name("%s.%d.%d.tmp" % (
        p.stem, os.getpid(), time.time_ns() % 1000000))
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)


def _claim_meta(ws, meta):
    """v8.0: atomically CLAIM a task id by creating its meta file with
    O_CREAT|O_EXCL. Returns True when this caller owns the id; False when
    another process created the file first (the caller bumps its id and
    retries). Fallback when the fd dance is impossible: exists()+write."""
    p = _meta_path(ws, meta["id"])
    blob = json.dumps(meta, ensure_ascii=False, indent=1)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        # exotic filesystem without EXCL support - degrade to the old
        # best-effort path (rare, single machine, advisory anyway)
        if p.exists():
            return False
        _write_meta(ws, meta)
        return True


def start(ws, cmd, timeout=3600, on_done=None, origin="repl", approved=False):
    """Start `cmd` in the workspace on a daemon thread.
    Returns (task_id, error).

    v6.3 security: the command goes through nova_security.screen() BEFORE
    any process is spawned. "deny"-level (destructive/system) commands are
    refused in every mode; "confirm"-level commands are refused unless the
    caller vouches for them (`approved=True`, i.e. an interactive user
    answered yes - the web face can only pass approved=True when secure
    mode is OFF). Every attempt, allowed or not, lands in the audit log.
    The shell=True execution itself is unchanged (pipes/redirections must
    keep working); the risk is now contained by screening + audit."""
    cmd = str(cmd or "").strip()
    if not cmd:
        return ("", "no command given")
    if nsec is not None:
        scr = nsec.screen(cmd)
        if scr["verdict"] == "deny":
            nsec.audit(ws, "bg", cmd, origin=origin, verdict="deny",
                       reason="; ".join(scr["reasons"]))
            return ("", "blocked by security: " + "; ".join(scr["reasons"]))
        if scr["verdict"] == "confirm" and not approved:
            nsec.audit(ws, "bg", cmd, origin=origin, verdict="deny",
                       reason="; ".join(scr["reasons"]) + " (not approved)")
            return ("", "needs confirmation: " + "; ".join(scr["reasons"]) +
                        "  (run it in the terminal to approve)")
        if scr["verdict"] == "confirm" and approved and origin == "web" \
                and nsec.is_secure(ws):
            # v6.7: the docstring promised this gate but nothing enforced
            # it - secure mode must block web-origin confirm commands
            # even when the caller vouches approved=True.
            nsec.audit(ws, "bg", cmd, origin=origin, verdict="deny",
                       reason="; ".join(scr["reasons"]) + " (secure mode)")
            return ("", "blocked by secure mode: web-origin confirm commands "
                        "are refused")
        nsec.audit(ws, "bg", cmd, origin=origin, verdict=scr["verdict"],
                   reason="; ".join(scr["reasons"]))
    with _LOCK:
        # v6.8.1 fix: the running-count was snapshotted BEFORE the lock -
        # two concurrent starts both measured 3 running and both passed
        # (the v6.7 "fix" moved only the comparison). list_tasks runs
        # inside the lock now.
        running = [t for t in list_tasks(ws) if t.get("status") == "running"]
        if len(running) >= MAX_CONCURRENT:
            return ("", f"too many background tasks running (cap {MAX_CONCURRENT}) - "
                        "check /bg list")
        # v6.5: id allocation + first meta write are one atomic step (RLock
        # re-entry) - two concurrent starts used to be able to grab the SAME
        # id and clobber each other's meta/log/_PROCS entry.
        # v7.14.1: the RLock only spans THIS process, but .nova/bg is
        # shared by the REPL + web server - if the freshly picked meta
        # file already exists on disk (the other process started a task
        # in between), bump the id until it is genuinely free.
        # v8.0: the bump loop alone was still a check-then-act race (both
        # processes can pass exists()==False before either writes) - the
        # final write now goes through an O_CREAT|O_EXCL claim, so one
        # process ALWAYS wins and the loser bumps its id instead of
        # clobbering the winner's task record.
        bg_dir(ws).mkdir(parents=True, exist_ok=True)
        tid = _next_id(ws)
        while True:
            meta = {"id": tid, "cmd": cmd[:300], "started": int(time.time()),
                    "status": "running", "exit": None, "dur": None}
            if _claim_meta(ws, meta):
                break
            m = re.match(r"b(\d+)", tid)
            tid = f"b{int(m.group(1)) + 1:04d}"
        started_ts = meta["started"]     # captured BEFORE the thread runs

    def work():
        buf = []
        t0 = time.time()
        code = None
        try:
            proc = subprocess.Popen(
                cmd, shell=True, cwd=str(ws),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                start_new_session=(os.name != "nt"),
                # A packaged windowed .exe has no console of its own, so
                # each background command would otherwise flash a brand
                # new black cmd.exe window on Windows even though its
                # output is already being captured via the pipes above.
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               if os.name == "nt" else 0))
            with _LOCK:
                _PROCS[tid] = proc
            # record the pid so a crashed session can still tell the
            # difference between alive (other process) and dead
            try:
                _write_meta(ws, {"id": tid, "cmd": cmd[:300],
                                 "started": started_ts, "status": "running",
                                 "exit": None, "dur": None, "pid": proc.pid})
            except OSError:
                pass
            # v6.2.1 fix: the old code called proc.wait(timeout=...) only
            # AFTER the read loop hit EOF - a silent/hung child (tail -f,
            # stuck npm install, deadlocked build) never reached the timeout
            # and ran forever, permanently leaking one of the MAX_CONCURRENT
            # slots. A watchdog now enforces the deadline and kills the
            # whole process group; EOF then ends the reader naturally.
            killed_by_timeout = [False]
            # v6.7: a falsy timeout (None/0) used to disable the watchdog
            # completely - a silent child then ran forever holding a slot
            # (the exact v6.2.1 bug class, resurging through any caller
            # passing None). Falsy now means the default; >24h is clamped.
            eff_timeout = timeout if isinstance(timeout, (int, float)) \
                and timeout and timeout > 0 else 3600
            eff_timeout = min(eff_timeout, 24 * 3600)
            if eff_timeout:
                def _watchdog():
                    try:
                        proc.wait(timeout=eff_timeout)
                    except subprocess.TimeoutExpired:
                        killed_by_timeout[0] = True
                        _kill_proc(proc)
                threading.Thread(target=_watchdog, daemon=True,
                                 name="nova-bg-watchdog-" + tid).start()
            try:
                while True:
                    chunk = proc.stdout.read(4096) if proc.stdout else ""
                    if not chunk:
                        break
                    if sum(len(b) for b in buf) < MAX_OUTPUT:
                        buf.append(chunk)
                code = proc.wait(timeout=30)
                if killed_by_timeout[0]:
                    code = -1
                    buf.append("\n[bg] killed after %ss timeout" % eff_timeout)
            except subprocess.TimeoutExpired:
                _kill_proc(proc)
                code = -1
                buf.append("\n[bg] killed after %ss timeout" % (eff_timeout or timeout))
        except OSError as e:
            buf.append("\n[bg] failed to start: " + str(e))
            code = None
        finally:
            with _LOCK:
                _PROCS.pop(tid, None)
            dur = round(time.time() - t0, 1)
            try:
                logp = _log_path(ws, tid)
                logp.write_text("".join(buf)[-MAX_OUTPUT:], encoding="utf-8")
                # v6.8.1: record the FINISHED time - the crash-recovery
                # announcement filters by it (a task started by a crashed
                # session always has started < the new session's cursor,
                # so filtering by `started` never announced anything).
                _write_meta(ws, {"id": tid, "cmd": cmd[:300],
                                 "started": started_ts,
                                 "finished": int(time.time()),
                                 "status": "finished" if code == 0
                                 else ("failed" if code else "died"),
                                 "exit": code, "dur": dur})
            except OSError:
                pass
            if on_done:
                try:
                    on_done(get_task(ws, tid) or {"id": tid, "status": "finished"})
                except Exception as e:
                    if nova_log is not None:
                        nova_log.soft("bg.on_done", e)          # v6.3: no more silent swallow

    th = threading.Thread(target=work, daemon=True, name="nova-bg-" + tid)
    th.start()
    return (tid, "")


def _kill_proc(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _alive_windows(pid):
    """v6.3: real Windows liveness check (the old code always answered
    'alive', so a crashed session's dead jobs stayed 'running' for ever
    and kept nothing useful - but also never surfaced as 'died').
    PROCESS_QUERY_LIMITED_INFORMATION via ctypes, no psutil:
      - OpenProcess fails w/ ERROR_INVALID_PARAMETER (87) -> no such pid
      - GetExitCodeProcess != STILL_ACTIVE (259)          -> exited
      - anything else (access denied, ctypes missing)     -> assume alive"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_INVALID_PARAMETER = 87
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                            int(pid))
        if not h:
            return k32.GetLastError() != ERROR_INVALID_PARAMETER
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception as e:
        if nova_log is not None:
            nova_log.soft("bg.alive_windows", e)
        return True                     # unsure -> old behaviour


def _alive(pid):
    """Best-effort liveness probe for stale 'running' entries."""
    if pid is None:
        return True
    if os.name == "nt":                  # v6.3: real check on Windows too
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    # v6.7: kill(pid, 0) succeeds for a ZOMBIE - a crashed session's job
    # whose shell exited but was never reaped (container subreaper) stayed
    # "running" forever, permanently eating a MAX_CONCURRENT slot.
    try:
        st = Path("/proc/%d/stat" % int(pid)).read_text(encoding="utf-8")
        after = st.rsplit(")", 1)[1].split()
        if after and after[0] == "Z":
            return False
    except Exception:
        pass
    return True


def list_tasks(ws):
    """All tasks newest-first; stale 'running' entries whose process is
    gone are marked 'died' (crash recovery)."""
    out = []
    try:
        metas = sorted(bg_dir(ws).glob("b*.json"), reverse=True)
    except OSError:
        return []
    for p in metas:
        try:
            meta = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            if nova_log is not None:
                nova_log.soft("bg.list_tasks.json", e, msg=str(p.name))
            continue
        if not isinstance(meta, dict) or not meta.get("id"):
            continue
        if meta.get("status") == "running":
            pid = meta.get("pid")
            if pid is not None:
                alive = _alive(pid)
            else:
                # v6.5: a crash in the spawn window (kill -9 / power loss
                # between the first and the pid meta write) left a pid-less
                # "running" entry that _alive(None) called alive FOREVER -
                # it kept eating one of the MAX_CONCURRENT slots. The pid
                # is written milliseconds after spawn, so a no-pid entry
                # older than 2 minutes is a dead spawn window.
                try:
                    age = int(time.time()) - int(meta.get("started") or 0)
                except (TypeError, ValueError):
                    age = 10 ** 9
                alive = age < 120
            if not alive:
                meta["status"] = "died"
                meta["exit"] = meta.get("exit")
                try:
                    _write_meta(ws, meta)
                except OSError:
                    pass
        out.append(meta)
    return out


def get_task(ws, tid):
    for meta in list_tasks(ws):
        if meta.get("id") == tid:
            return meta
    return None


def tail_log(ws, tid, lines=60):
    meta = get_task(ws, tid)
    if not meta:
        return None, f"no such task: {tid}"
    p = _log_path(ws, tid)
    if not p.is_file():
        return (meta, "(no output yet)")
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return (meta, "(cannot read log: %s)" % e)
    rows = content.splitlines()
    return (meta, "\n".join(rows[-int(lines):]))


def _kill_pid(pid):
    """Kill a task started by a PREVIOUS process, by recorded pid - the
    whole process GROUP on POSIX (the task was started with
    start_new_session=True; killing just the shell pid orphaned every
    child, which kept holding the slot and the output pipes)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), 9)
            except (ProcessLookupError, PermissionError, OSError):
                os.kill(pid, 9)
        return True
    except OSError:
        return False


def _pid_matches_cmd(pid, cmd):
    """v6.7: best-effort identity check before a cross-process kill - the
    OS recycles pids, and the v6.5 guard only covered the in-process
    handle path. POSIX: the target's /proc cmdline must contain the
    recorded shell command (the recorded pid IS the `sh -c <cmd>` shell).
    Windows: the recorded shell is cmd.exe, so the image must be cmd.exe
    (anything else means the pid was reused). Cannot verify -> False
    (never signal a stranger)."""
    cmd = str(cmd or "").strip()
    if not cmd:
        return False
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k32.OpenProcess.restype = ctypes.c_void_p
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                int(pid))
            if not h:
                return False
            try:
                size = ctypes.c_ulong(1024)
                buf = ctypes.create_unicode_buffer(1024)
                if k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0,
                                                  buf, ctypes.byref(size)):
                    exe = (buf.value or "").replace("/", "\\") \
                        .rsplit("\\", 1)[-1].lower()
                    return exe == "cmd.exe"
                return False
            finally:
                k32.CloseHandle(ctypes.c_void_p(h))
        raw = Path("/proc/%d/cmdline" % int(pid)).read_bytes()
        argv = [a.decode("utf-8", "replace") for a in raw.split(b"\x00") if a]
        if not argv:
            return False
        cl = " ".join(argv)
        if cmd in cl or cl in cmd:
            # v6.8.1: substring matching in BOTH directions authorized a
            # kill of a recycled pid running a SUPERSET command (recorded
            # 'npm test', squatter runs 'npm test2' -> "npm test" in
            # "npm test2" is True!). Require the sh -c payload to carry
            # the recorded command as a WORD-BOUNDED substring.
            # v8.0: the LEFT boundary is enforced too - 'npm test' used
            # to match inside 'xnpm test' (recorded cmd authorized a kill
            # of an unrelated squatter command).
            import re as _re
            return bool(_re.search(
                r"(?<![\w-])" + _re.escape(cmd) + r"(?![\w-])", cl))
        return False
    except Exception:
        return False


def kill(ws, tid):
    meta = get_task(ws, tid)
    if not meta:
        return "no such task: " + str(tid)
    if meta.get("status") != "running":
        return f"task {tid} is not running (status: {meta.get('status')})"
    with _LOCK:
        proc = _PROCS.get(tid)
    if proc:
        if proc.poll() is None:
            _kill_proc(proc)
            return f"killed {tid}"
        # v6.5: the process handle exists but has JUST exited - never fall
        # through to the recorded-pid path here, a recycled OS pid could
        # make us kill a completely innocent process group.
        return f"task {tid} already finished (exit {proc.returncode})"
    # started by a previous process: try by recorded pid
    pid = meta.get("pid")
    if pid:
        if not _alive(pid):
            return f"task {tid} is no longer running"
        # v6.7: identity check - a recycled OS pid must never let us
        # SIGKILL an innocent process group (the in-process handle path
        # got this guard in v6.5; the cross-process path had none).
        if not _pid_matches_cmd(pid, meta.get("cmd", "")):
            try:
                meta["status"] = "died"
                _write_meta(ws, meta)
            except OSError:
                pass
            return (f"pid {pid} no longer matches task {tid}'s command "
                    "(the pid was reused by another program) - nothing was "
                    "signalled, the task was marked as died")
        if _kill_pid(pid):
            return f"signalled pid {pid} of {tid}"
        return f"cannot signal pid {pid} of {tid}"
    return f"task {tid} runs in another process - kill it there"


def newly_finished(ws, since_ts=0):
    """Tasks that finished after `since_ts` - the REPL / web poll uses
    this for the 'your background job is done' notification.
    v6.8.1: filters by the meta's `finished` timestamp now - the old
    `started` comparison NEVER fired for a job started by a previous
    (crashed) session, because its started time is always older than the
    new session's cursor - exactly the crash-recovery case the
    persistent task store exists for. Metas from older versions have no
    `finished` field and keep the legacy `started` fallback."""
    out = []
    for meta in list_tasks(ws):
        if meta.get("status") not in ("finished", "failed", "died"):
            continue
        ref = meta.get("finished", meta.get("started", 0))
        try:
            if int(ref or 0) > int(since_ts):
                out.append(meta)
        except (TypeError, ValueError):
            continue
    return out


def prune(ws):
    """Delete task files older than MAX_AGE_S. Silent, best-effort."""
    cutoff = time.time() - MAX_AGE_S
    try:
        for p in bg_dir(ws).glob("b*.*"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                continue
    except OSError:
        pass


def clear_all(ws):
    shutil.rmtree(bg_dir(ws), ignore_errors=True)
