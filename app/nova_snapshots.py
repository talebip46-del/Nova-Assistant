#!/usr/bin/env python3
# =====================================================================
#  Nova Code - snapshot & unlimited undo (v5.0)
#
#  Every apply batch becomes a persistent UNIT under .nova/snapshots/:
#    auto/<id>/    - one per apply; holds the BEFORE content of every
#                    file it touched (self-contained copies, no reliance
#                    on .nova_backups) + meta.json
#    manual/<id>/  - full workspace checkpoints made with /snapshot
#
#  /undo pops auto units newest-first: a backup file is restored, a file
#  that was NEW is deleted. There is no "last batch only" limit any more -
#  you can walk back through dozens of applies (bounded by retention:
#  MAX_AUTO_UNITS units, MAX_MANUAL_UNITS checkpoints).
#
#  Manual checkpoints (/snapshot <label>) capture the whole workspace
#  (minus .nova*, .git, ignored + secret paths, oversized files) and are
#  restored wholesale with /restore <id|label>.
#
#  Pure standard library, atomic meta writes, fail-soft: a broken unit is
#  skipped, a broken restore is reported - nothing crashes the session.
# =====================================================================
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

try:
    import nova_atomic as natom
except Exception:
    natom = None

SNAP_SUB = "snapshots"
AUTO_KIND = "auto"
MANUAL_KIND = "manual"
MAX_AUTO_UNITS = 50
MAX_MANUAL_UNITS = 10
MAX_FILE_BYTES = 2_000_000       # per-file content stored in a unit
MAX_CHECKPOINT_FILES = 4000      # safety cap for manual checkpoints
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def root(ws, kind=AUTO_KIND):
    return Path(ws) / ".nova" / SNAP_SUB / kind


def _safe_abs(ws, rel):
    """Absolute path for a workspace-relative path, escape-proof."""
    wsr = Path(ws).resolve()
    p = (wsr / str(rel)).resolve()
    if p != wsr and wsr not in p.parents:
        raise ValueError("path escapes the workspace: " + str(rel))
    return p


_SEQ = 0
_ID_LOCK = threading.Lock()


def _new_id():
    """Collision-free unit id even for batches pushed in the same
    millisecond (a fast /auto loop does exactly that) - and across the
    REPL + web double process (v6.8.1: pid + uuid entropy in the tail;
    two processes CAN hit the same millisecond and sequence)."""
    global _SEQ
    with _ID_LOCK:
        _SEQ = (_SEQ + 1) % 1000
    ms = int(time.time() * 1000) % 1000
    tail = f"{os.getpid() % 100:02d}{uuid.uuid4().hex[:2]}" 
    return (time.strftime("%Y%m%d_%H%M%S") + f"_{ms:03d}{_SEQ:03d}"
            + tail)


def _store_name(idx, rel):
    """Flat, collision-free name for a file stored inside a unit dir."""
    return "%03d__%s" % (idx, str(rel).replace("/", "__").replace("\\", "__"))


def _write_meta(unit, meta):
    """v8.0: written via nova_atomic - the hand-rolled tmp+rename had no
    fsync, so a crash published a truncated/zero-length meta.json and the
    whole undo unit was silently skipped by _read_meta/list_units. The
    error string is returned to the caller (used to be dropped)."""
    text = json.dumps(meta, ensure_ascii=False, indent=1)
    if natom is not None:
        return natom.write_text_atomic(unit / "meta.json", text)
    # degraded fallback (no nova_atomic importable): unique scratch name
    tmp = unit / ("meta.json.%d.%d.tmp" % (os.getpid(), time.time_ns() % 1000000))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, unit / "meta.json")
        return ""
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        return str(e)


def _read_meta(unit):
    try:
        meta = json.loads((unit / "meta.json").read_text(encoding="utf-8", errors="replace"))
        if isinstance(meta, dict) and meta.get("id") and isinstance(meta.get("files"), list):
            return meta
    except Exception:
        pass
    return None


# --------------------------------------------------------------- auto units
def push_auto_unit(ws, batch, note=""):
    """Register one apply batch as an undo unit.
    batch = [(abs_target_path, abs_backup_path_or_None)]; backup None means
    the file was NEW (undo must delete it). Returns (unit_id, error)."""
    uid = _new_id()
    unit = root(ws, AUTO_KIND) / uid
    ws_res = Path(ws).resolve()
    files, errs = [], []
    for i, (target, backup) in enumerate(batch):
        try:
            rel = Path(target).resolve().relative_to(ws_res).as_posix()
        except (ValueError, OSError):
            errs.append("outside workspace, skipped: " + str(target))
            continue
        if backup:
            try:
                unit.mkdir(parents=True, exist_ok=True)
                # v8.0: honor the same size cap build_checkpoint enforces -
                # an uncapped copy2 duplicated huge (even GB-scale) files
                # into .nova/snapshots on every apply of that file.
                if os.path.getsize(backup) > MAX_FILE_BYTES:
                    # v8.0: same convention as build_checkpoint - skip=True
                    # means "existed but deliberately not captured"; the
                    # undo entry leaves the current file alone instead of
                    # duplicating (possibly GB-scale) content per apply.
                    files.append({"rel": rel, "backup": None, "skip": True})
                    errs.append(f"{rel}: too large to snapshot ("
                                f"> {MAX_FILE_BYTES} bytes) - undo will "
                                "keep the current file")
                    continue
                name = _store_name(i, rel)
                shutil.copy2(str(backup), str(unit / name))
                files.append({"rel": rel, "backup": name})
            except OSError as e:
                errs.append(f"{rel}: {e}")
        else:
            files.append({"rel": rel, "backup": None})
    if not files:
        return ("", "nothing snapshotable in this batch")
    try:
        unit.mkdir(parents=True, exist_ok=True)
        _write_meta(unit, {"id": uid, "kind": AUTO_KIND, "ts": time.time(),
                           "note": str(note or "")[:200], "files": files})
    except OSError as e:
        shutil.rmtree(unit, ignore_errors=True)
        return ("", str(e))
    _prune(ws)
    return (uid, "; ".join(errs))


def list_units(ws, kind=None):
    """All units (newest first): [{meta..., 'dir': Path}]. Broken units
    (unreadable meta) are skipped, never raised."""
    out = []
    kinds = (AUTO_KIND, MANUAL_KIND) if kind is None else (kind,)
    for k in kinds:
        base = root(ws, k)
        try:
            dirs = [d for d in base.iterdir() if d.is_dir()] if base.is_dir() else []
        except OSError:
            dirs = []
        for d in dirs:
            meta = _read_meta(d)
            if meta:
                meta = dict(meta)
                meta["dir"] = d
                out.append(meta)
    out.sort(key=lambda m: str(m.get("id", "")), reverse=True)
    return out


def undo_units(ws, n=1):
    """Undo the n newest auto units. Returns
    {'restored': [(action, rel)...], 'errors': [str], 'undone': [id]}"""
    n = max(1, int(n))
    res = {"restored": [], "errors": [], "undone": []}
    for meta in list_units(ws, AUTO_KIND)[:n]:
        d = meta["dir"]
        errs_before = len(res["errors"])
        for f in meta["files"]:
            rel, bk = f.get("rel"), f.get("backup")
            try:
                target = _safe_abs(ws, rel)
                if f.get("skip") and not bk:
                    # v8.0: deliberately-not-captured (too large / secret)
                    # - undo must NOT delete the current file either
                    res["restored"].append(("kept", rel))
                elif bk:
                    src = d / str(bk)
                    # v7.1.0: the basename/"__"-prefix dance here was DEAD
                    # code (computed, never used - restore uses d/str(bk))
                    if src.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src), str(target))
                        res["restored"].append(("restored", rel))
                    else:
                        res["errors"].append(f"backup copy missing: {rel}")
                else:
                    if target.is_file() or target.is_symlink():
                        target.unlink()
                        res["restored"].append(("deleted", rel))
            except (ValueError, OSError) as e:
                res["errors"].append(f"{rel}: {e}")
        # v6.2.1 fix: the unit used to be destroyed even when the restore
        # had errors (missing backup copies) - a half-restored workspace
        # with NO retry path. Keep a failed unit on disk so /undo can be
        # retried (a later /snapshot prune still caps the stack).
        if len(res["errors"]) == errs_before:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
            res["undone"].append(meta.get("id", "?"))
        else:
            res["undone"].append(meta.get("id", "?") + " (kept - restore had errors)")
    return res


# --------------------------------------------------------------- manual checkpoints
def build_checkpoint(ws, ignore=None):
    """Walk the workspace and capture {rel: content|None} (None = existed
    but skipped: too big / secret / unreadable). Skips .nova*, .git,
    ignored dirs and .novaignore matches - the agent must never snapshot
    its own bookkeeping."""
    ws = Path(ws).resolve()
    state = {}
    skipped = []
    count = 0

    def skip_dir(name):
        return name in (".git", ".nova") or name.startswith(".nova") \
            or name in ("node_modules", "__pycache__", "venv", ".venv")

    for r, dirs, names in os.walk(ws):
        dirs[:] = sorted(d for d in dirs if not skip_dir(d) and not d.startswith("."))
        if ignore is not None:
            relroot = Path(r).resolve().relative_to(ws).as_posix()
            dirs[:] = [d for d in dirs
                       if not (ignore.matches((relroot + "/" + d).lstrip("/"), is_dir=True)
                               if relroot != "." else ignore.matches(d, is_dir=True))]
        for n in sorted(names):
            if n.startswith("."):
                continue
            rel = (Path(r).resolve().relative_to(ws) / n).as_posix()
            if ignore is not None and ignore.matches(rel):
                continue
            count += 1
            if count > MAX_CHECKPOINT_FILES:
                # v6.7 fix: cap-overflow files used to be dropped WITHOUT a
                # skip entry - restore_manual's sweep then saw them as
                # "created after the snapshot" and DELETED any whose mtime
                # was >= ts, although they existed all along.
                state[rel] = None
                skipped.append(rel + " (file cap)")
                continue
            p = Path(r) / n
            try:
                size = p.stat().st_size
                low = n.lower()
                if size > MAX_FILE_BYTES or low.endswith(SECRET_SUFFIXES) \
                        or low in ("id_rsa", "id_ed25519") or ".env" in low:
                    state[rel] = None
                    skipped.append(rel + " (too big or secret)" if size > MAX_FILE_BYTES
                                   else rel + " (secret)")
                    continue
                # v6.2.1 fix: binary files (png/sqlite/wheels...) decoded with
                # errors="replace" were silently CORRUPTED (BOM bytes + LF
                # newline translation) and /restore then overwrote the user's
                # originals with the mojibake. Detect NUL in the head; store
                # binaries as raw bytes and write them back byte-exact.
                with open(p, "rb") as fh:
                    head = fh.read(8192)
                if b"\x00" in head:
                    state[rel] = p.read_bytes()
                else:
                    # v6.7 fix: read_text() used universal-newline mode
                    # (CRLF -> LF) and errors="replace" (non-UTF-8 ->
                    # U+FFFD) - /restore then rewrote EVERY text file with
                    # corrupted bytes even when untouched (git saw the
                    # whole tree modified; latin-1 data was mangled).
                    # newline="" keeps the line endings; a non-UTF-8 file
                    # is stored as raw bytes and restored byte-exact.
                    try:
                        with open(p, "r", encoding="utf-8",
                                  errors="strict", newline="") as tf:
                            state[rel] = tf.read()
                    except (UnicodeDecodeError, ValueError):
                        state[rel] = p.read_bytes()
            except OSError as e:
                state[rel] = None
                skipped.append(f"{rel} ({e})")
    return state, skipped


def make_manual(ws, label="", ignore=None):
    """Full workspace checkpoint. Returns (unit_id, error, skipped)."""
    uid = _new_id()
    unit = root(ws, MANUAL_KIND) / uid
    state, skipped = build_checkpoint(ws, ignore)
    files = []
    try:
        unit.mkdir(parents=True, exist_ok=True)
        for i, (rel, content) in enumerate(sorted(state.items())):
            if content is None:
                files.append({"rel": rel, "backup": None, "skip": True})
                continue
            name = _store_name(i, rel)
            # v6.2.1: bytes content = a binary file captured raw; write it
            # back byte-exact instead of forcing utf-8 text on it
            if isinstance(content, bytes):
                (unit / name).write_bytes(content)
            else:
                with open(unit / name, "w", encoding="utf-8", newline="") as _fh:
                    _fh.write(content)
            files.append({"rel": rel, "backup": name, "skip": False})
        merr = _write_meta(unit, {"id": uid, "kind": MANUAL_KIND,
                                  "ts": time.time(),
                                  "label": str(label or "")[:80],
                                  "files": files})
        if merr:
            shutil.rmtree(unit, ignore_errors=True)
            return ("", merr, skipped)
    except OSError as e:
        shutil.rmtree(unit, ignore_errors=True)
        return ("", str(e), skipped)
    _prune(ws)
    return (uid, "", skipped)


def find_manual(ws, ref):
    """Manual checkpoint by id or by label (label wins if unique)."""
    units = list_units(ws, MANUAL_KIND)
    for m in units:
        if m.get("id") == ref:
            return m
    hits = [m for m in units if str(m.get("label", "")) == ref]
    return hits[0] if len(hits) == 1 else None


def restore_manual(ws, meta, ignore=None):
    """Make the workspace match a manual checkpoint again:
    - files in the snapshot are rewritten (or deleted if snapshot says
      they did not exist);
    - files created AFTER the snapshot that the checkpoint WOULD have
      captured are deleted too - the honest 'back in time' semantics.
    v6.2.1 fix: the sweep used to delete ANYTHING not in the snapshot -
    including files the builder deliberately skips (dotfiles like .env,
    .novaignore matches, node_modules ...). '/restore' permanently
    destroyed secrets and dependency trees it had never captured. The
    sweep now skips exactly the same set the builder skips.
    Returns {'written': [rel], 'deleted': [rel], 'skipped': [rel],
             'errors': [str]}"""
    res = {"written": [], "deleted": [], "skipped": [], "errors": []}
    d = meta["dir"]
    known = set()
    for f in meta["files"]:
        rel, bk = f.get("rel"), f.get("backup")
        known.add(rel)
        try:
            target = _safe_abs(ws, rel)
            if bk and not f.get("skip"):
                src = d / str(bk)
                if src.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(target))
                    res["written"].append(rel)
                else:
                    res["errors"].append("snapshot copy missing: " + rel)
            elif f.get("skip"):
                # v6.5 fix: skip=True means "existed when the checkpoint was
                # taken but was deliberately NOT captured" (too big, secret
                # like .pem/.key/id_rsa, or unreadable). The old code funnelled
                # these into the delete branch - /restore permanently
                # destroyed the user's keys, model weights and big dumps.
                # They are left exactly as they are now.
                res["skipped"].append(rel)
            else:
                # no backup and no skip flag = the file did not exist when
                # the snapshot was taken -> honest back-in-time deletion
                if target.is_file() or target.is_symlink():
                    target.unlink()
                    res["deleted"].append(rel)
        except (ValueError, OSError) as e:
            res["errors"].append(f"{rel}: {e}")
    # files created after the checkpoint: not in it, not bookkeeping,
    # and NOT in the never-captured classes (dotfiles / ignored / venvs)
    ws = Path(ws).resolve()
    try:
        ts = int(meta.get("ts", 0))
    except (TypeError, ValueError):
        ts = 0

    def never_captured(rel):
        """Same classes build_checkpoint always skips - deleting these was
        exactly the v6.2 data-loss bug. NOTE: the builder skips dotfiles
        ANYWHERE (dir or file), so every '.'-part counts, not just dirs."""
        parts = rel.split("/")
        if any(part.startswith(".") for part in parts):
            return True
        if any(part in ("node_modules", "__pycache__", "venv", ".venv")
               for part in parts):
            return True
        if ignore is not None:
            try:
                return ignore.matches(rel)
            except Exception:
                return False
        return False

    for r, dirs, names in os.walk(ws):
        # prune the same dir classes the builder prunes (do not descend)
        dirs[:] = [x for x in dirs if x != ".git" and not x.startswith(".nova")
                   and x not in ("node_modules", "__pycache__", "venv", ".venv")
                   and not x.startswith(".")]
        for n in names:
            rel = (Path(r).resolve().relative_to(ws) / n).as_posix()
            if rel in known or rel.startswith(".nova/") or rel.startswith(".git/"):
                continue
            if never_captured(rel):
                continue
            p = Path(r) / n
            try:
                if ts and p.stat().st_mtime > float(ts):
                    p.unlink()
                    res["deleted"].append(rel + " (created after the snapshot)")
            except OSError:
                continue
    return res


# --------------------------------------------------------------- retention
def _prune(ws):
    for kind, cap in ((AUTO_KIND, MAX_AUTO_UNITS), (MANUAL_KIND, MAX_MANUAL_UNITS)):
        units = list_units(ws, kind)
        for meta in units[cap:]:
            shutil.rmtree(str(meta["dir"]), ignore_errors=True)
        # v6.7: a crash between the unit mkdir and the meta write left a
        # metaless dir that list_units skips - and that _prune therefore
        # never removed, piling up dead megabytes under .nova/snapshots.
        # Remove metaless unit dirs older than a day.
        try:
            base = root(ws, kind)
            if base.is_dir():
                cutoff = time.time() - 86400
                for d in base.iterdir():
                    if d.is_dir() and _read_meta(d) is None:
                        try:
                            if d.stat().st_mtime < cutoff:
                                shutil.rmtree(str(d), ignore_errors=True)
                        except OSError:
                            continue
        except OSError:
            pass


def stats(ws):
    autos = list_units(ws, AUTO_KIND)
    manuals = list_units(ws, MANUAL_KIND)
    return {"auto_units": len(autos), "manual_checkpoints": len(manuals),
            "oldest_auto": autos[-1]["id"] if autos else "",
            "newest_auto": autos[0]["id"] if autos else ""}
