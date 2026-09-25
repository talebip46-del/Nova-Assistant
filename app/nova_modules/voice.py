#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - Nova Voice (v6.1)
#
#  Text-to-speech and speech-to-text through pluggable engines:
#
#    openai_compat  POST {base}/audio/speech  {model, input, voice}
#                   (LocalAI, Kokoro-FastAPI, any OpenAI-shaped server)
#                   STT: POST {base}/audio/transcriptions (multipart)
#                   -> works with whisper.cpp server / LocalAI whisper
#    xtts           Coqui XTTS API server: POST /tts_to_file?text=...
#                   (clone-ready XTTS-v2 engines behind this shape)
#    coqui          Coqui TTS / Mozilla TTS HTTP server:
#                   POST /api/tts {"text": ...} -> wav bytes
#                   (both projects share the same wire shape)
#    bark           bark-server: POST /v1/generate {"text": ...}
#                   -> wav bytes (Suno Bark served locally)
#    piper          LOCAL binary: echo text | piper --model x --output_file y
#                   (list args, NO shell, hard timeout). The model can
#                   be a plain path OR a 'file:<name>' voice from the
#                   local/voice model folder (v6.1).
#    offline        zero-setup built-in: a clean synthesized WAV chime
#                   sequence written with the stdlib `wave` module.
#                   Honest placeholder - it proves the pipeline and it
#                   is NOT speech; real voices need one of the engines.
#
#  All engine failures become ModuleError with short readable messages.
# =====================================================================
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from pathlib import Path

from nova_modules import ModuleError, module_data_dir

MAX_TEXT = 5000
MAX_AUDIO = 12_000_000            # STT upload cap (~12 MB)
HTTP_TIMEOUT = 120
HISTORY_CAP = 200

_UA = {"User-Agent": "NovaAssistant"}


def _cfg_url(cfg):
    url = str(cfg.get("url") or "").strip().rstrip("/")
    if not url or not url.lower().startswith(("http://", "https://")):
        raise ModuleError("this engine needs a server URL in the module assignment")
    return url


def sniff_format(raw):
    """Magic-based format detection - never trust a filename."""
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        return "wav"
    if raw[:3] == b"ID3" or (len(raw) > 2 and raw[0] == 0xFF and
                             (raw[1] & 0xE0) == 0xE0):
        return "mp3"
    if raw[:4] == b"OggS":
        return "ogg"
    if raw[:4] == b"fLaC":
        return "flac"
    return "bin"


# --------------------------------------------------------------- engines
def _post_audio(url, payload, timeout=HTTP_TIMEOUT):
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **_UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(MAX_AUDIO)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read(300).decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise ModuleError("HTTP %d from TTS engine %s" % (e.code, detail[:160])) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise ModuleError("cannot reach the TTS engine (%s)"
                          % str(getattr(e, "reason", e))[:120]) from None


def tts_openai_compat(ws, text, cfg):
    url = _cfg_url(cfg) + "/audio/speech"
    payload = {"model": cfg.get("model") or "tts-1",
               "input": text, "voice": cfg.get("voice") or "alloy",
               "response_format": "wav"}
    raw = _post_audio(url, payload)
    if len(raw) < 100:
        raise ModuleError("TTS engine returned no audio")
    fmt = sniff_format(raw)
    if fmt == "bin":
        raise ModuleError("TTS engine returned an unknown audio format")
    return raw, fmt


def tts_xtts(ws, text, cfg):
    base = _cfg_url(cfg)
    url = (base + "/tts_to_file?text=" +
           urllib.parse.quote(text[:MAX_TEXT], safe="") +
           "&language=" + urllib.parse.quote(cfg.get("lang", "fa") or "fa", safe=""))
    if cfg.get("speaker"):
        url += "&speaker_wav=" + urllib.parse.quote(str(cfg["speaker"])[:300], safe="")
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read(MAX_AUDIO)
    except urllib.error.HTTPError as e:
        raise ModuleError("HTTP %d from XTTS server" % e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise ModuleError("cannot reach the XTTS server (%s)"
                          % str(getattr(e, "reason", e))[:120]) from None
    if len(raw) < 100:
        raise ModuleError("XTTS returned no audio")
    return raw, sniff_format(raw)


def tts_coqui(ws, text, cfg):
    """Coqui TTS HTTP server (python -m TTS.server.server) and the older
    Mozilla TTS server - both POST /api/tts {"text": ...} -> wav bytes."""
    base = _cfg_url(cfg)
    payload = {"text": text[:MAX_TEXT]}
    if cfg.get("model"):
        payload["model_id"] = str(cfg["model"])[:200]
    if cfg.get("speaker"):
        payload["speaker_id"] = str(cfg["speaker"])[:200]
    if cfg.get("lang"):
        payload["language_id"] = str(cfg["lang"])[:40]
    raw = _post_audio(base + "/api/tts", payload)
    if len(raw) < 100:
        raise ModuleError("Coqui/Mozilla TTS returned no audio")
    fmt = sniff_format(raw)
    if fmt == "bin":
        raise ModuleError("Coqui/Mozilla TTS returned an unknown audio format")
    return raw, fmt


def tts_bark(ws, text, cfg):
    """bark-server: POST {base}/v1/generate {"text": ...} -> wav bytes
    (a local Suno Bark server). 'voice' maps to history_prompt."""
    base = _cfg_url(cfg)
    url = base if base.endswith("/v1/generate") else base + "/v1/generate"
    payload = {"text": text[:MAX_TEXT]}
    if cfg.get("voice"):
        payload["history_prompt"] = str(cfg["voice"])[:200]
    raw = _post_audio(url, payload)
    if len(raw) < 100:
        raise ModuleError("bark-server returned no audio")
    fmt = sniff_format(raw)
    if fmt == "bin":
        raise ModuleError("bark-server returned an unknown audio format")
    return raw, fmt


def _resolve_voice_model(ws, ref):
    """'file:<name>' or a bare file name -> (entry, abs_path) of a voice
    model found in the model folders (local/voice, ...). None when the
    ref is just a plain filesystem path, no match, or scanning fails."""
    if not ref or "/" in ref or "\\" in ref:
        return None
    import nova_localmodels as lmodels
    want = str(ref).strip()
    if want.startswith(lmodels.LOCAL_PREFIX):
        want = want[len(lmodels.LOCAL_PREFIX):]
    want = want.strip().strip("\"'").lower()
    if not want:
        return None
    try:
        for e in lmodels.scan_dirs(lmodels.model_dirs(ws)):
            fname = Path(e.get("file", "")).name.lower()
            if e.get("name", "").lower() == want or \
                    fname in (want, want + ".onnx", want + ".gguf"):
                return e, e.get("file", "")
    except Exception:
        return None
    return None


def tts_piper(ws, text, cfg):
    exe = str(cfg.get("path") or "piper").strip() or "piper"
    model = str(cfg.get("model") or "").strip()
    if not model:
        raise ModuleError("piper needs a voice model path in the assignment (model field)")
    resolved = _resolve_voice_model(ws, model) if \
        (model.startswith("file:") or "/" not in model and "\\" not in model) \
        else None
    if resolved is not None:
        entry, path = resolved
        if entry.get("format") != "onnx":
            raise ModuleError(
                "'%s' is an LLM brain (%s) - piper needs a voice model "
                "(.onnx) from the local/voice folder"
                % (entry.get("name"), entry.get("format")))
        model = path
    elif model.startswith("file:"):
        raise ModuleError("no voice model '%s' in the model folders "
                          "(drop the .onnx into local/voice)" % model)
    out_dir = module_data_dir(ws, "voice")
    out_path = out_dir / ("piper-%s.wav" % uuid.uuid4().hex[:10])
    cmd = [exe, "--model", model, "--output_file", str(out_path)]
    try:
        proc = subprocess.run(cmd, input=text.encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=120)
    except FileNotFoundError:
        raise ModuleError("piper binary not found - install it or set the path field") from None
    except subprocess.TimeoutExpired:
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ModuleError("piper timed out after 120s") from None
    if proc.returncode != 0 or not out_path.is_file():
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise ModuleError("piper failed: %s" % (err[:200] or proc.returncode))
    try:
        return out_path.read_bytes(), "wav"
    finally:
        # v6.5: piper's temp file was left behind on EVERY call - it showed
        # up as a duplicate in list_history and bypassed the history cap.
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass


# The offline chime: a small pentatonic arpeggio, 16-bit mono 22050 Hz.
# Deterministic, dependency-free, and instantly recognizable as
# "Nova talked to me" while being honest about not being speech.
_TONES = (523.25, 659.25, 783.99, 1046.50)     # C5 E5 G5 C6


def tts_offline(ws, text, cfg=None):
    rate = 22050
    dur = 0.16
    fade = int(rate * 0.03)
    frames = bytearray()
    for i, f in enumerate(_TONES):
        n = int(rate * dur)
        for s in range(n):
            env = 1.0
            if s < fade:
                env = s / fade
            elif s > n - fade:
                env = (n - s) / fade
            val = int(32767 * 0.28 * env *
                      (0.6 * (s * f / rate % 1.0) + 0.4) *
                      (1.0 - i * 0.12))
            frames += int(val).to_bytes(2, "little", signed=True)
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue(), "wav"


TTS_ENGINES = {"openai_compat": tts_openai_compat, "xtts": tts_xtts,
               "coqui": tts_coqui, "bark": tts_bark,
               "piper": tts_piper, "offline": tts_offline}


# --------------------------------------------------------------- entry
def synthesize(ws, text, cfg=None, want_engine=None):
    """Text -> audio file in the voice gallery.
    {name, path, engine, fmt, bytes, note}."""
    text = str(text or "").strip()
    if not text:
        raise ModuleError("empty text")
    if len(text) > MAX_TEXT:
        raise ModuleError("text too long (%d chars, %d max)" % (len(text), MAX_TEXT))
    cfg = cfg or {}
    engine = want_engine or cfg.get("backend") or "offline"
    if engine not in TTS_ENGINES:
        raise ModuleError("unknown TTS engine '%s'" % engine)
    raw, fmt = TTS_ENGINES[engine](ws, text, cfg)
    name = "tts-%s-%s.%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6], fmt)
    path = module_data_dir(ws, "voice") / name
    # v6.2.1: atomic write - a crash mid-write used to leave a truncated
    # tts-*.wav that list_history happily displayed
    tmp = path.with_suffix(".part")
    tmp.write_bytes(raw)
    tmp.replace(path)
    note = ""
    if engine == "offline":
        note = ("موتور آفلاین: یک چایم تصویری نواخته شد (نه گفتار واقعی) - "
                "برای صدای واقعی موتور Piper / XTTS / Coqui / Bark / LocalAI "
                "را متصل کنید")
    # v6.5: the prune glob 'tts-*.???' could not match '.flac' (4-char
    # suffix), so flac output grew the gallery forever while list_history
    # happily displayed it. Match every format sniff_format accepts.
    # v6.7: also sweep orphaned .part files (>1h) - a crash between the
    # tmp write and the replace used to leak them forever.
    base_dir = module_data_dir(ws, "voice")
    old = [f for f in base_dir.glob("tts-*.*")
           if f.suffix.lower() in (".wav", ".mp3", ".ogg", ".flac")]
    old.sort()
    if len(old) > HISTORY_CAP:
        for f in old[:len(old) - HISTORY_CAP]:
            try:
                f.unlink()
            except OSError:
                pass
    try:
        for f in base_dir.glob("*.part"):
            if time.time() - f.stat().st_mtime > 3600:
                f.unlink()
    except OSError:
        pass
    return {"engine": engine, "name": name, "path": str(path),
            "fmt": fmt, "bytes": len(raw), "note": note}


# --------------------------------------------------------------- STT
def _multipart(field, filename, content, extra=None):
    boundary = "----NovaBoundary" + uuid.uuid4().hex
    # v6.2.1 fix: the filename used to be spliced into the header raw - a
    # value with " or CR/LF (upload body, local only) could inject multipart
    # headers toward the configured STT server. Sanitize it hard.
    filename = re.sub(r"[^\w.\- ]", "_", str(filename or "audio.wav"))[:120]
    parts = []
    for k, v in (extra or {}).items():
        parts.append("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                     % (boundary, k, v))
    parts.append("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n"
                 % (boundary, field, filename))
    body = ("".join(parts)).encode("utf-8") + content + \
        ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    return body, "multipart/form-data; boundary=" + boundary


def transcribe(ws, audio_bytes, cfg=None, filename="audio.wav"):
    """Audio bytes -> text via an OpenAI-compatible /audio/transcriptions
    (whisper.cpp server, LocalAI whisper, ...)."""
    raw = bytes(audio_bytes or b"")
    if len(raw) < 100:
        raise ModuleError("audio file too small")
    if len(raw) > MAX_AUDIO:
        raise ModuleError("audio file too large (12 MB max)")
    if sniff_format(raw) == "bin":
        raise ModuleError("unsupported audio format (wav/mp3/ogg/flac only)")
    cfg = cfg or {}
    if cfg.get("backend") not in (None, "openai_compat"):
        raise ModuleError("STT currently needs an openai_compat engine "
                          "(whisper.cpp server / LocalAI)")
    base = _cfg_url(cfg) if cfg.get("url") else "http://127.0.0.1:8080/v1"
    body, ctype = _multipart("file", filename or "audio.wav", raw,
                             {"model": cfg.get("model") or "whisper-1"})
    try:
        req = urllib.request.Request(
            base + "/audio/transcriptions", data=body,
            headers={"Content-Type": ctype, **_UA})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise ModuleError("HTTP %d from STT engine" % e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise ModuleError("cannot reach the STT engine (%s)"
                          % str(getattr(e, "reason", e))[:120]) from None
    except ValueError:
        raise ModuleError("STT engine returned invalid JSON") from None
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        raise ModuleError("STT engine returned no text")
    return text.strip()[:MAX_TEXT]


def wav_info(raw):
    """(seconds, channels, rate) for a WAV blob - or None. Used by the
    UI to label uploads before they are sent."""
    import io
    if sniff_format(raw) != "wav":
        return None
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            rate = w.getframerate() or 1
            return {"seconds": round(w.getnframes() / rate, 2),
                    "channels": w.getnchannels(), "rate": rate}
        # pragma: no cover
    except Exception:
        return None


def list_history(ws, cap=40):
    base = module_data_dir(ws, "voice", create=False)
    if not base.is_dir():
        return []
    out = []
    for f in base.iterdir():
        if f.suffix.lower() in (".wav", ".mp3", ".ogg", ".flac"):
            try:
                out.append({"name": f.name, "mtime": f.stat().st_mtime,
                            "bytes": f.stat().st_size})
            except OSError:
                continue
    out.sort(key=lambda e: -e["mtime"])
    return out[:cap]
