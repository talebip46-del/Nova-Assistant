#!/usr/bin/env python3
# =====================================================================
#  Nova Code - secretbox: real on-disk encryption with ZERO deps (v6.8)
#
#  Encrypts the conversation memory / transcripts at rest:
#    key       PBKDF2-HMAC-SHA256(passphrase, salt, 200k iters, 32B)
#    cipher    HMAC-SHA256 keystream in COUNTER mode (a PRF-based
#              stream cipher: for a 32-byte block i the pad is
#              HMAC(key, nonce || uint64(i)); the pad never repeats
#              for a given (key, nonce) and is never reused)
#    integrity encrypt-then-MAC: HMAC over magic+salt+nonce+ciphertext
#              verified with hmac.compare_digest BEFORE decrypting
#  File layout:  b"NVSB1" | salt(16) | nonce(16) | ct | tag(32)
#
#  This is stdlib-only crypto for LOCAL at-rest privacy (someone with
#  the disk but not the passphrase reads nothing). It is not a substitute
#  for a reviewed AES construction, and it cannot protect a machine the
#  attacker controls while the passphrase is loaded.
# =====================================================================
import hashlib
import hmac as _hmac
import os
import struct
import threading
import time
from pathlib import Path

try:  # v7.14.1: prefer the battle-tested unique-tmp helper
    import nova_atomic as _natom
except Exception:
    _natom = None

MAGIC = b"NVSB1"
SALT_LEN = 16
NONCE_LEN = 16
TAG_LEN = 32
PBKDF2_ITERS = 200_000
BLOCK = 32                      # HMAC-SHA256 output size
MAX_FILE = 64 * 1024 * 1024     # 64 MB safety cap for sealed blobs


def new_salt():
    return os.urandom(SALT_LEN)


def new_nonce():
    return os.urandom(NONCE_LEN)


def derive_key(passphrase, salt):
    """32-byte key from a human passphrase + stored salt."""
    if isinstance(passphrase, str):
        passphrase = passphrase.encode("utf-8")
    if not passphrase:
        raise ValueError("empty passphrase")
    return hashlib.pbkdf2_hmac("sha256", passphrase, salt, PBKDF2_ITERS)


def _keystream(key, nonce, length):
    """HMAC-SHA256 CTR-mode pad. Pure generator, no memory blowup."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        msg = nonce + struct.pack(">Q", counter)
        out.extend(_hmac.new(key, msg, hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def seal_bytes(data, key, salt=None, nonce=None):
    """Encrypt-then-MAC. Returns the full blob to write to disk."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("seal_bytes needs bytes")
    data = bytes(data)
    salt = salt or new_salt()
    nonce = nonce or new_nonce()
    pad = _keystream(key, nonce, len(data))
    ct = bytes(a ^ b for a, b in zip(data, pad))
    tag = _hmac.new(key, MAGIC + salt + nonce + ct, hashlib.sha256).digest()
    return MAGIC + salt + nonce + ct + tag


def open_bytes(blob, key):
    """Verify tag first, then decrypt. Returns plaintext bytes.
    Raises ValueError on any corruption / wrong key."""
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < len(MAGIC) + SALT_LEN + NONCE_LEN + TAG_LEN:
        raise ValueError("not a secretbox blob")
    blob = bytes(blob)
    if blob[:len(MAGIC)] != MAGIC:
        raise ValueError("bad magic (not a sealed file)")
    off = len(MAGIC)
    salt = blob[off:off + SALT_LEN]
    off += SALT_LEN
    nonce = blob[off:off + NONCE_LEN]
    off += NONCE_LEN
    ct = blob[off:-TAG_LEN]
    tag = blob[-TAG_LEN:]
    want = _hmac.new(key, MAGIC + salt + nonce + ct, hashlib.sha256).digest()
    if not _hmac.compare_digest(want, tag):
        raise ValueError("integrity check failed (wrong passphrase or corrupted file)")
    pad = _keystream(key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, pad))


# --------------------------------------------------------------- files
def seal_file(path, plaintext, key):
    """Seal `plaintext` (str or bytes) over `path` atomically.
    v7.14.1 fix: the scratch name used to be a SHARED `path + ".tmp~"` -
    two processes (REPL + web server) sealing the same store raced on it:
    one rename yanked the other's tmp away (FileNotFoundError -> that
    session silently never persisted) or a torn blob got published and
    HMAC verification then reported the whole store as locked. The unique
    per-process scratch name kills the race; the tmp is also cleaned up
    on failure now. Returns the blob size."""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    blob = seal_bytes(plaintext, key)
    # v8.0: the sealed blob is now fsync'd before the rename via the
    # atomic helper - a crash used to publish a zero-length/partial blob
    # and HMAC verification then reported the WHOLE store as corrupted
    # (total data loss, not just the last save).
    if _natom is not None:
        err = _natom.write_bytes_atomic(Path(path), blob)
        if err:
            raise OSError(err)
        return len(blob)
    # degraded fallback: pid + thread + clock unique scratch + fsync
    tmp = "%s.tmp%d" % (path, (os.getpid() * 7919
                        + threading.get_ident() % 100000
                        + int(time.time() * 1000)) % 1000000)
    try:
        with open(tmp, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return len(blob)


def open_file(path, key):
    """Read + verify + decrypt a sealed file. Returns bytes.
    Raises OSError / ValueError as-is (caller shows a clean message)."""
    size = os.path.getsize(path) if os.path.exists(path) else 0
    if size > MAX_FILE:
        raise ValueError(f"sealed file too large ({size} bytes)")
    with open(path, "rb") as fh:
        return open_bytes(fh.read(), key)


def is_sealed(path):
    """Magic check WITHOUT any key (used to decide load paths)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


# --------------------------------------------------------------- key cache
_KEY_CACHE = {}
_last_key = {"pass": None, "salt": None, "key": None}


def cached_key(passphrase, salt):
    """Derive the key with a 1-entry cache keyed on (passphrase, SALT).
    v6.8.1 fix: the salt is part of the cache key now - nova_memory
    derives a workspace-path salt, so two workspaces with the same
    passphrase need DIFFERENT keys; the old cache ignored the salt and
    sealed the second workspace with the first one's key (silently
    unreadable file). PBKDF2 at 200k iters is ~0.1-0.3 s - the cache
    keeps the REPL snappy and dies with the process."""
    if (_last_key["pass"] == passphrase and _last_key["salt"] == salt
            and _last_key["key"] is not None):
        return _last_key["key"]
    key = derive_key(passphrase, salt)
    _last_key["pass"] = passphrase
    _last_key["salt"] = salt
    _last_key["key"] = bytearray(key)   # v8.0: mutable, scrubbable cache
    return key


def forget_key():
    """Best-effort scrub of the cached key. v8.0: the key is cached as a
    bytearray and zeroed IN PLACE - the old code built bytearray(bytes)
    (a fresh copy), zeroed the copy and left the original 32 bytes of
    key material alive in memory until GC."""
    _last_key["pass"] = None
    _last_key["salt"] = None
    k = _last_key["key"]
    if k is not None:
        try:
            for i in range(len(k)):
                k[i] = 0
        except Exception:
            pass
    _last_key["key"] = None


# --------------------------------------------------------------- self-test
def self_test():
    """Round-trip + tamper + wrong-key checks. Returns (ok, msg)."""
    try:
        k = derive_key("correct horse battery staple", new_salt())
        msg = "سلام Nova 🚀 line1\nline2 " + "x" * 1000
        blob = seal_bytes(msg.encode("utf-8"), k)
        if open_bytes(blob, k).decode("utf-8") != msg:
            return (False, "round-trip mismatch")
        bad = bytearray(blob)
        bad[len(MAGIC) + 40] ^= 0x01     # flip one ciphertext bit
        try:
            open_bytes(bytes(bad), k)
            return (False, "tampered blob accepted")
        except ValueError:
            pass
        k2 = derive_key("other", blob[len(MAGIC):len(MAGIC) + SALT_LEN])
        try:
            open_bytes(blob, k2)
            return (False, "wrong key accepted")
        except ValueError:
            pass
        return (True, "ok")
    except Exception as e:
        return (False, f"self-test failed: {e}")
