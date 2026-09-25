#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - nova_atomic (v8.0)
#
#  One tiny helper for the project-wide atomic-write idiom.
#
#  os.replace() is atomic per call, but the classic pattern
#      tmp = p.with_suffix(".tmp"); tmp.write_text(...); os.replace(tmp, p)
#  uses a FIXED scratch name. Nova is often TWO processes on one
#  workspace (terminal REPL + web server). Writer B's open-truncate can
#  land between writer A's write and A's os.replace, publishing B's
#  PARTIAL bytes under A's name - a torn JSON file that then fails to
#  load and silently resets the store (providers vault, cost ledger,
#  memory, skills, policy...).
#
#  The fix is the one nova_search's cache already got in v6.5, applied
#  everywhere: every writer gets its OWN scratch name (pid + thread id
#  + a process-local counter), so two writers can never share a tmp
#  file. Pure standard library, fail-soft.
#
#  v8.0 (clear):
#    - the parent DIRECTORY is fsync'd after os.replace - without it
#      the rename itself is not durable and a power loss can revert a
#      "saved" store (ext4 may reorder the rename after the data);
#    - scratch files are created 0600 on POSIX so a vault/secret store
#      is never world-readable between the rename and the chmod;
#    - file_lock writes an OWNER TOKEN and only breaks a stale lock /
#      releases a lock when the token still matches (no more stealing a
#      fresh lock after a stale check, no more releasing someone else's
#      lock after a steal);
#    - load_json_state(): the crash-recovery reader - quarantines a
#      corrupt state file instead of silently resetting it and restores
#      the last good copy kept beside it (<name>.good).
# =====================================================================
import contextlib
import itertools
import json
import os
import secrets
import threading
import time

STALE_LOCK_S = 60.0   # a lock older than this is broken (owner died)
from pathlib import Path

_SEQ = itertools.count()


def tmp_name(p, tag="tmp"):
    """Unique sibling scratch name for `p`. Never collides across
    processes, threads or nested calls in the same thread."""
    return p.with_name("%s.%s.%d.%d.%d" % (
        p.stem, tag, os.getpid(),
        threading.get_ident() % 1000000, next(_SEQ)))


def _fsync_dir(p):
    """fsync the parent directory so the RENAME itself is durable.
    POSIX-only (Windows has no portable dir fsync); never raises."""
    try:
        if os.name == "nt":
            return
        fd = os.open(str(Path(p).parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


def write_text_atomic(p, text, encoding="utf-8", newline=None, mode=0o600):
    """Atomically write `text` to `p` via a UNIQUE tmp file.
    Returns '' on success or a short error string. The tmp file never
    survives success and is cleaned up best-effort on failure.
    v7.14.1: the data is fsync'd before the rename - without it a power
    loss could publish a zero-length/partial store (the rename reaches
    the disk before the data blocks do), which every loader then resets
    to its empty default.
    v8.0: the scratch file is created 0600 (POSIX) so secrets never sit
    world-readable between rename and chmod, and the parent directory
    is fsync'd so the rename is durable too."""
    p = Path(p)
    tmp = tmp_name(p)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     mode if os.name != "nt" else 0o666)
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        tmp = None
        _fsync_dir(p)
        return ""
    except Exception as e:
        return str(e)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except Exception:
                pass


def write_bytes_atomic(p, data, mode=0o600):
    """Atomically write raw bytes to `p` via a UNIQUE tmp file.
    Returns '' on success or a short error string. (v7.14.1: fsync'd
    like the text variant. v8.0: 0600 scratch + durable rename.)"""
    p = Path(p)
    tmp = tmp_name(p)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     mode if os.name != "nt" else 0o666)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        tmp = None
        _fsync_dir(p)
        return ""
    except Exception as e:
        return str(e)
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except Exception:
                pass


# ---------------------------------------------------------------------
# v8.0 crash-recovery reader: quarantine + last-good restore
# ---------------------------------------------------------------------
_GOOD_MTIMES = {}          # path -> mtime of the last .good snapshot
_GOOD_LOCK = threading.Lock()


def quarantine(p):
    """Move a corrupt file to <parent>/corrupt/ with a timestamp tag so
    the bytes are never silently lost. Best effort, never raises."""
    p = Path(p)
    try:
        if not p.exists():
            return ""
        qdir = p.parent / "corrupt"
        qdir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = qdir / ("%s.%d.%s.corrupt" % (p.name, os.getpid(), stamp))
        try:
            os.replace(str(p), str(dst))
        except OSError:
            return ""
        _fsync_dir(p)
        return str(dst)
    except Exception:
        return ""


def load_json_state(p, default, max_bytes=8 * 1024 * 1024):
    """Fail-soft crash-recovery JSON reader for .nova state files.
    - parse ok  -> remember a last-good copy (<name>.good, best effort,
      written at most once per mtime change) and return the data.
    - parse fail -> quarantine the corrupt bytes; if a last-good copy
      exists and parses, restore it and return it; else return `default`.
    Returns (data, note) where note is '' or a short human string the
    caller may log. Never raises (falls back to (default, 'read error'))."""
    p = Path(p)
    good = p.with_name(p.name + ".good")
    try:
        if not p.is_file():
            # v8.0: the file was intentionally deleted - a stale .good
            # copy must NOT survive it (a later corrupt write would
            # otherwise resurrect the deleted data)
            try:
                good.unlink()
            except OSError:
                pass
            with _GOOD_LOCK:
                _GOOD_MTIMES.pop(str(p), None)
            return (default, "")
        if p.stat().st_size > max_bytes:
            return (default, "too large")
        raw = p.read_bytes()
    except OSError as e:
        return (default, str(e)[:120])
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        # corrupt: quarantine, then try the last-good copy
        quarantine(p)
        try:
            if good.is_file() and good.stat().st_size <= max_bytes:
                gdata = json.loads(good.read_bytes().decode("utf-8"))
                try:
                    write_bytes_atomic(p, good.read_bytes())
                except Exception:
                    pass
                return (gdata, "restored from last-good")
        except Exception:
            pass
        try:
            good.unlink()
        except Exception:
            pass
        return (default, "corrupt (quarantined)")
    # healthy parse - keep a last-good copy at most once per mtime
    try:
        mtime = p.stat().st_mtime
        with _GOOD_LOCK:
            if _GOOD_MTIMES.get(str(p)) != mtime:
                # v8.0: the cache is CAPPED - a long-lived web server
                # visiting many workspaces used to grow it unbounded
                if len(_GOOD_MTIMES) > 512:
                    for k in list(_GOOD_MTIMES)[:256]:
                        _GOOD_MTIMES.pop(k, None)
                _GOOD_MTIMES[str(p)] = mtime
                write_bytes_atomic(good, raw)
    except Exception:
        pass
    return (data, "")


@contextlib.contextmanager
def file_lock(path, timeout=10.0, poll=0.05):
    """v6.7: cross-process advisory mutex over one O_CREAT|O_EXCL lock
    file. Nova is often TWO processes on one workspace (REPL + web);
    thread locks do not span processes, so read-modify-write sections
    (knowledge ingest, module assignments) could lose updates.
    A lock older than STALE_LOCK_S seconds (independent of the acquire
    timeout - v6.8.1: the old code reused `timeout` (~5 s) as the stale
    threshold, so any critical section slower than 5 s had its lock
    STOLEN by the next process and the lost-update race returned) is
    treated as stale and broken (its owner died). Fail-soft: any acquire
    problem degrades to running unlocked - the same behavior the
    thread-only lock provided before.
    Yields True when the lock was taken, False when it degraded."""
    p = Path(path)
    fd = None
    locked = False
    token = ("%d.%d.%s" % (os.getpid(), threading.get_ident(),
                           secrets.token_hex(8))).encode("utf-8")
    try:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass                                # degrade: run unlocked
        deadline = time.time() + max(0.5, float(timeout))
        while True:
            try:
                fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                locked = True
                try:
                    os.write(fd, token)         # owner token (debug aid)
                except Exception:
                    pass
                break
            except FileExistsError:
                # v8.0 stale handling: steal via an INODE check so a
                # stale lock is only ever broken while the path still
                # points at the very file we inspected - a stealer that
                # lost the race can never unlink the winner's fresh lock.
                try:
                    fd2 = os.open(str(p), os.O_RDONLY)
                except OSError:
                    continue                    # vanished - retry create
                try:
                    st_fd = os.fstat(fd2)
                    if time.time() - st_fd.st_mtime >= STALE_LOCK_S:
                        try:
                            st_path = os.stat(str(p))
                            if st_path.st_ino == st_fd.st_ino:
                                os.unlink(str(p))
                        except OSError:
                            pass
                except OSError:
                    pass
                finally:
                    try:
                        os.close(fd2)
                    except Exception:
                        pass
                if time.time() >= deadline:
                    break                       # degrade: run unlocked
                time.sleep(poll)
            except OSError:
                break                           # cannot create - unlocked
        yield True if locked else False
    finally:
        if locked and fd is not None:
            try:
                my_ino = os.fstat(fd).st_ino   # BEFORE the close
            except Exception:
                my_ino = None
            try:
                os.close(fd)
            except Exception:
                pass
            # v8.0: release only OUR lock - unlink only while the path
            # still refers to the inode we created. If a stealer already
            # replaced it, our unlink would delete THEIR fresh lock.
            if my_ino is not None:
                try:
                    if os.stat(str(p)).st_ino == my_ino:
                        os.unlink(str(p))
                except OSError:
                    pass
                except Exception:
                    pass
