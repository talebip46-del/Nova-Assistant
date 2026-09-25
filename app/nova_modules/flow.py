#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - Nova Flow, the integration hub (v6.0)
#
#  The "everything works TOGETHER" engine. A workflow is a JSON list of
#  steps; each step calls ONE module (or one primitive) and publishes
#  its output as a variable the later steps can template in:
#
#      {{idea}}            the whole output of step 'idea'
#      {{img.path}}        one field of it (dict traversal, no code)
#
#  Step types:
#    prompt      one LLM turn (assistant module brain)
#    crew        multi-role team: N role turns + a synthesis turn
#                (CrewAI-style, roles defined inline)
#    code_ask    LLM turn grounded with the repo style map + Knowledge
#                context (the "code aware" node)
#    voice / photo / pixel   the creative modules
#    knowledge   search the local document brain
#    http        GET a URL (http/https only, small, short timeout)
#    condition   compare two values; optionally JUMP to a step id
#                (the LangGraph-style branch) - loop-capped
#    transform   pure template into a variable
#    delay       pause (<= 30s)
#
#  Safety: NO eval / exec anywhere - templating is regex + dict walk;
#  runs execute in a daemon thread with per-run status files; every
#  failure lands in the run log, never on the caller's stack.
# =====================================================================
import json
import re
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import socket
from pathlib import Path

from nova_modules import ModuleError

MAX_STEPS = 50
MAX_NAME = 40
MAX_EXEC = 500                 # hard cap on node executions per run
MAX_HTTP_BODY = 200_000
MAX_DELAY = 30.0
# v6.2.1 fix: the bare int() made a non-numeric NOVA_FLOW_LLM_TIMEOUT kill
# the whole app at import time (web server included). Fail-soft instead.
try:
    LLM_TIMEOUT = max(5, int(str(__import__("os").environ.get(
        "NOVA_FLOW_LLM_TIMEOUT", "300") or 300)))
except (TypeError, ValueError):
    LLM_TIMEOUT = 300

NAME_RE = re.compile(r"^[A-Za-z0-9_\- ]{1,40}$")
ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*)\s*\}\}")

STEP_TYPES = ("prompt", "crew", "code_ask", "voice", "photo", "pixel",
              "knowledge", "http", "condition", "transform", "delay")

_OLLAMA_BASE = "http://localhost:11434"


# --------------------------------------------------------------- model
def flows_dir(ws):
    d = Path(ws) / ".nova" / "flows"
    d.mkdir(parents=True, exist_ok=True)
    return d


def runs_dir(ws):
    d = flows_dir(ws) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean_name(raw):
    name = str(raw or "").strip()
    if not NAME_RE.match(name):
        raise ModuleError("flow name must be 1-40 letters/digits/space/-/_")
    return name


def validate(flow):
    """Workflow dict -> normalized copy. Raises ModuleError with the
    FIRST problem found (short, readable, no tracebacks)."""
    if not isinstance(flow, dict):
        raise ModuleError("flow must be a JSON object")
    name = _clean_name(flow.get("name"))
    steps = flow.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ModuleError("flow needs a non-empty 'steps' list")
    if len(steps) > MAX_STEPS:
        raise ModuleError("too many steps (%d max)" % MAX_STEPS)
    ids = set()
    out = []
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            raise ModuleError("step %d is not an object" % (i + 1))
        sid = str(st.get("id") or "").strip()
        if not ID_RE.match(sid):
            raise ModuleError("step %d: bad id '%s'" % (i + 1, sid[:40]))
        if sid in ids:
            raise ModuleError("duplicate step id '%s'" % sid)
        ids.add(sid)
        stype = str(st.get("type") or "").strip().lower()
        if stype not in STEP_TYPES:
            raise ModuleError("step '%s': unknown type '%s'" % (sid, stype))
        withf = st.get("with") or {}
        if not isinstance(withf, dict):
            raise ModuleError("step '%s': 'with' must be an object" % sid)
        if len(withf) > 24:
            raise ModuleError("step '%s': too many 'with' fields" % sid)
        clean_with = {}
        for k, v in withf.items():
            if not ID_RE.match(str(k)):
                raise ModuleError("step '%s': bad 'with' key '%s'" % (sid, k))
            if isinstance(v, str):
                if len(v) > 20_000:
                    raise ModuleError("step '%s': field '%s' too long" % (sid, k))
            elif isinstance(v, (int, float, bool)) or v is None:
                pass
            else:
                raise ModuleError("step '%s': field '%s' must be text/number"
                                  % (sid, k))
            clean_with[str(k)] = v
        if stype == "prompt" and not str(clean_with.get("text", "")).strip():
            raise ModuleError("step '%s': prompt needs text" % sid)
        if stype == "condition":
            op = str(clean_with.get("op", "not_empty")).strip().lower()
            if op not in ("eq", "ne", "contains", "gt", "lt", "empty",
                          "not_empty"):
                raise ModuleError("step '%s': bad condition op '%s'" % (sid, op))
        out.append({"id": sid, "type": stype, "with": clean_with})
    return {"name": name, "steps": out}


def save(ws, flow):
    norm = validate(flow)
    p = flows_dir(ws) / (norm["name"].replace(" ", "_") + ".json")
    # v6.5: "my flow" and "my_flow" map to the SAME file (space->underscore).
    # Saving the second used to silently destroy the first. Overwriting the
    # same flow (normal edit) still works.
    if p.is_file():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            old = None
        if isinstance(old, dict) and str(old.get("name", "")) != norm["name"]:
            raise ModuleError(
                "a flow named '%s' already uses the file '%s' - pick another "
                "name" % (old.get("name"), p.name))
    # v8.7: unique-scratch atomic write - the fixed '.json.part' name
    # had NO cross-process lock at all; two faces saving the same flow
    # could publish torn JSON and the flow silently vanished.
    try:
        import nova_atomic as _natom
    except Exception:
        _natom = None
    if _natom is not None:
        err = _natom.write_text_atomic(
            p, json.dumps(norm, ensure_ascii=False, indent=1),
            encoding="utf-8")
        if err:
            raise OSError(err)
    else:                               # natom missing - best effort
        tmp = p.with_suffix(".json.part")
        tmp.write_text(json.dumps(norm, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(p)
    return norm


def delete(ws, name):
    # v6.2.1 fix: name validation was missing here (unlike get/save), so
    # "../../victim" resolved OUTSIDE the flows dir and unlinked any
    # *.json file the process could reach - reachable from the web via
    # POST /api/flow/delete. Same rule as everywhere else now.
    name = _clean_name(name)
    p = flows_dir(ws) / (name.replace(" ", "_") + ".json")
    if p.is_file():
        p.unlink()
        return True
    return False


def list_flows(ws, cap=50):
    out = []
    for p in sorted(flows_dir(ws).glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            out.append({"name": data.get("name", p.stem),
                        "steps": len(data["steps"]),
                        "types": [s.get("type", "?") for s in data["steps"]][:10]})
        if len(out) >= cap:
            break
    return out


def get(ws, name):
    name = _clean_name(name)
    p = flows_dir(ws) / (name.replace(" ", "_") + ".json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return validate(data)
    except ModuleError:
        return None


# --------------------------------------------------------------- templating
def substitute(text, variables, depth=0):
    """{{var}} / {{var.key.sub}} -> string. Unknown refs stay as-is
    (visible in the UI instead of vanishing). NO eval - ever."""
    if depth > 5 or not isinstance(text, str):
        return text

    def repl(m):
        parts = m.group(1).split(".")
        cur = variables.get(parts[0])
        for key in parts[1:]:
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return m.group(0)
        if cur is None:
            return m.group(0)
        if isinstance(cur, dict):
            cur = cur.get("text") or cur.get("path") or json.dumps(
                cur, ensure_ascii=False)[:400]
        return str(cur)

    return TEMPLATE_RE.sub(repl, str(text))


def _fill(withf, variables):
    return {k: substitute(v, variables) if isinstance(v, str) else v
            for k, v in withf.items()}


# --------------------------------------------------------------- LLM bridge
def _ollama_chat(model, messages, timeout=None, base=None):
    """One NON-streaming /api/chat call. Kept local to flow so the hub
    works without touching the agent's session/heartbeat machinery."""
    base = (base or _OLLAMA_BASE).rstrip("/")
    payload = {"model": model, "messages": messages, "stream": False}
    try:
        req = urllib.request.Request(
            base + "/api/chat", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": "NovaAssistant"})
        with urllib.request.urlopen(req, timeout=timeout or LLM_TIMEOUT) as resp:
            data = json.loads(resp.read(20_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise ModuleError("Ollama HTTP %d (model installed?)" % e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise ModuleError("cannot reach Ollama (%s)"
                          % str(getattr(e, "reason", e))[:120]) from None
    except ValueError:
        raise ModuleError("Ollama returned invalid JSON") from None
    msg = data.get("message") if isinstance(data, dict) else None
    text = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(text, str):
        raise ModuleError("Ollama returned no message content")
    return text


def _find_file_entry(ws, model):
    """'file:<name>' / bare name -> a scanned model-file entry (or None)."""
    import nova_localmodels as lmodels
    want = str(model or "").strip()
    if want.startswith(lmodels.LOCAL_PREFIX):
        want = want[len(lmodels.LOCAL_PREFIX):]
    want = want.strip().strip("\"'").lower()
    if not want:
        return None
    try:
        for e in lmodels.scan_dirs(lmodels.model_dirs(ws)):
            fname = Path(e.get("file", "")).name.lower()
            if e.get("name", "").lower() == want or \
                    fname in (want, want + ".gguf", want + ".onnx",
                              want + ".safetensors"):
                return e
    except Exception:
        return None
    return None


def _file_chat_fn(ws, model):
    """A model FILE as the Flow assistant brain (v6.1 - the backend was
    declared in the module spec but never wired). Route order:
      1. import into Ollama (one-time, cached) - does not disturb any
         llama-server the main chat session may be running;
      2. spawn llama.cpp 'llama-server' on a free port (needs llama.cpp).
    Both failures become ONE clean ModuleError."""
    import nova_localmodels as lmodels
    entry = _find_file_entry(ws, model)
    if entry is None:
        raise ModuleError("no model file '%s' in the model folders "
                          "(local/, local/code, ...)" % model)
    if not entry.get("runnable"):
        raise ModuleError("'%s' is not a runnable LLM brain (%s)"
                          % (entry.get("name"),
                             entry.get("note") or entry.get("format")))
    ollama_name = None
    try:
        import nova as _nova
        ollama_name = _nova.import_gguf_to_ollama(entry, ws=ws, quiet=True)
    except Exception:
        ollama_name = None
    if ollama_name:
        def chat(system, text):
            msgs = ([{"role": "system", "content": system}] if system else []) + \
                [{"role": "user", "content": text}]
            return _ollama_chat(ollama_name, msgs)
        return chat
    try:
        handle = lmodels.start_llama_server(entry["file"])
    except lmodels.LocalModelError as e:
        raise ModuleError(
            "cannot run the model file '%s': %s"
            % (entry.get("name"), str(e)[:200])) from None
    base = handle["base"]

    def chat(system, text):
        msgs = ([{"role": "system", "content": system}] if system else []) + \
            [{"role": "user", "content": text}]
        return _openai_chat(base, "local", "", msgs)
    return chat


def _default_chat_fn(ws, cfg=None):
    """Build chat_fn(system, text) -> str from the assistant assignment.
    injectable -> fully testable without any server."""
    from nova_modules import assign as _assign
    cfg = cfg or _assign.resolve(ws, "assistant")
    backend = cfg.get("backend", "auto")
    if backend in ("auto", "ollama"):
        model = cfg.get("model") or ""
        if not model:
            import os
            model = (os.environ.get("NOVA_MODEL", "") or "").strip()
        if not model:
            model = _first_ollama_model()
        if not model:
            raise ModuleError("no Ollama model available - pull one or "
                              "assign a brain to the assistant module")

        def chat(system, text):
            msgs = ([{"role": "system", "content": system}] if system else []) + \
                [{"role": "user", "content": text}]
            return _ollama_chat(model, msgs)
        return chat
    if backend == "platform":
        url = (cfg.get("url") or "").rstrip("/")
        if not url:
            raise ModuleError("assistant platform backend needs a URL")

        def chat(system, text):
            msgs = ([{"role": "system", "content": system}] if system else []) + \
                [{"role": "user", "content": text}]
            return _openai_chat(url, cfg.get("model") or "default",
                                cfg.get("key", ""), msgs)
        return chat
    if backend == "file":
        return _file_chat_fn(ws, cfg.get("model"))
    if backend == "cloud":
        import nova_providers as providers
        name = str(cfg.get("model") or "").strip()
        prov_name, _, model = name.partition(":")
        if not model and providers is not None:
            try:
                pcfg = providers.resolve()
                return _cloud_chat_fn(pcfg, pcfg.get("model", ""))
            except Exception:
                raise ModuleError("cloud backend: set model as 'provider:model' "
                                  "(e.g. 'openai:gpt-4o-mini')") from None
        try:
            pcfg = providers.resolve(prov_name or None)
        except Exception as e:
            raise ModuleError(str(e)) from None
        return _cloud_chat_fn(pcfg, model)
    raise ModuleError("assistant brain '%s' is not usable inside Flow "
                      "(use ollama / file / platform / cloud)" % backend)


def _cloud_chat_fn(pcfg, model):
    import nova_providers as providers

    def chat(system, text):
        msgs = ([{"role": "system", "content": system}] if system else []) + \
            [{"role": "user", "content": text}]
        pieces = []
        for piece in providers.stream_chunks(pcfg, model, msgs, 0.4, LLM_TIMEOUT):
            pieces.append(piece)
        return "".join(pieces)
    return chat


def _openai_chat(base, model, key, messages, timeout=None):
    try:
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps({"model": model, "messages": messages,
                             "stream": False}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": "NovaAssistant",
                     **({"Authorization": "Bearer " + key} if key else {})})
        with urllib.request.urlopen(req, timeout=timeout or LLM_TIMEOUT) as resp:
            data = json.loads(resp.read(20_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise ModuleError("HTTP %d from the platform" % e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise ModuleError("cannot reach the platform (%s)"
                          % str(getattr(e, "reason", e))[:120]) from None
    except ValueError:
        raise ModuleError("platform returned invalid JSON") from None
    choices = data.get("choices") if isinstance(data, dict) else None
    if choices and isinstance(choices[0], dict):
        text = (choices[0].get("message") or {}).get("content")
        if isinstance(text, str):
            return text
    raise ModuleError("platform returned no message content")


def _first_ollama_model():
    try:
        req = urllib.request.Request(_OLLAMA_BASE + "/api/tags",
                                     headers={"User-Agent": "NovaAssistant"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            tags = json.loads(resp.read(4_000_000).decode("utf-8", "replace"))
        models = tags.get("models") if isinstance(tags, dict) else None
        if isinstance(models, list):
            for m in models:
                if isinstance(m, dict) and isinstance(m.get("name"), str) \
                        and m["name"] and "embed" not in m["name"].lower():
                    return m["name"]
    except Exception:
        pass
    return ""


# --------------------------------------------------------------- the engine
class _Run:
    def __init__(self, ws, flow, inputs, chat_fn=None):
        self.ws = ws
        self.flow = flow
        self.vars = {}
        for k, v in (inputs or {}).items():
            if ID_RE.match(str(k)) and isinstance(v, (str, int, float, bool)):
                self.vars[str(k)] = v
        self._chat_fn = chat_fn            # may stay None until an LLM node
        self.chat_fn = None                # resolved lazily by _chat()
        self.log = []
        self.status = "running"
        self.error = ""
        self.started = time.time()

    def _chat(self):
        """Resolve the assistant brain on FIRST LLM use - flows made of
        offline steps must run with no Ollama and no assignment at all."""
        if self.chat_fn is None:
            self.chat_fn = self._chat_fn or _default_chat_fn(self.ws)
        return self.chat_fn

    def fail(self, sid, msg):
        self.log.append({"id": sid, "type": "", "status": "failed",
                         "detail": str(msg)[:400], "ms": 0})
        self.status = "failed"
        self.error = str(msg)[:400]

    def run(self, on_step=None):
        """Execute the flow. `on_step` (optional) fires after EVERY log
        change so async runs can persist live progress (v6.2.1: the web
        status page used to show 0 steps until the whole run finished)."""
        jumps = {}
        for st in self.flow["steps"]:
            jumps[st["id"]] = st
        order = [st["id"] for st in self.flow["steps"]]
        idx = 0
        execs = 0
        per_step = {}
        while 0 <= idx < len(order):
            execs += 1
            if execs > MAX_EXEC:
                self.status = "failed"
                self.error = "too many step executions (loop?)"
                break
            sid = order[idx]
            per_step[sid] = per_step.get(sid, 0) + 1
            if per_step[sid] > 100:
                self.status = "failed"
                self.error = "step '%s' executed too often (loop?)" % sid
                break
            st = jumps.get(sid)
            if st is None:
                self.status = "failed"
                self.error = "jump target '%s' not found" % sid
                break
            t0 = time.time()
            try:
                result, next_hint = self._exec(st)
                self.log.append({"id": sid, "type": st["type"],
                                 "status": result.get("status", "done"),
                                 "detail": str(result.get("detail", ""))[:400],
                                 "ms": int((time.time() - t0) * 1000)})
                if on_step:
                    try:
                        on_step()
                    except Exception:
                        pass   # progress persistence must never stop a run
                if next_hint is not None:
                    if next_hint not in jumps:
                        raise ModuleError("jump to unknown step '%s'" % next_hint)
                    idx = order.index(next_hint)
                    continue
                if result.get("status") == "skip":
                    idx += 1
                    continue
                idx += 1
            except ModuleError as e:
                self.fail(sid, e)
                if on_step:
                    try:
                        on_step()
                    except Exception:
                        pass
                break
            except Exception as e:                 # engine bug -> honest log
                self.fail(sid, type(e).__name__ + ": " + str(e)[:200])
                if on_step:
                    try:
                        on_step()
                    except Exception:
                        pass
                break
        if self.status == "running":
            self.status = "done"
        self.finished = time.time()

    # one step ------------------------------------------------------
    def _exec(self, st):
        w = _fill(st["with"], self.vars)
        stype = st["type"]
        # lazy imports: modules must stay optional for the test suite
        if stype == "prompt":
            text = str(w.get("text", ""))
            sys_p = str(w.get("system", "") or "")
            out = self._chat()(sys_p, text)
            self.vars[st["id"]] = {"text": out}
            return {"detail": out[:200]}, None
        if stype == "code_ask":
            ctx = self._code_context()
            text = str(w.get("text", ""))
            out = self._chat()(str(w.get("system", "") or "You are a coding assistant."),
                               (ctx + "\n\n" if ctx else "") + text)
            self.vars[st["id"]] = {"text": out}
            return {"detail": out[:200]}, None
        if stype == "crew":
            return self._crew(st, w), None
        if stype == "voice":
            from nova_modules import voice, assign
            cfg = assign.resolve(self.ws, "voice")
            eng = str(w.get("engine", "") or "") or None
            r = voice.synthesize(self.ws, str(w.get("text", "")), cfg, want_engine=eng)
            self.vars[st["id"]] = r
            return {"detail": r["name"]}, None
        if stype == "photo":
            from nova_modules import photo, assign
            cfg = dict(assign.resolve(self.ws, "photo"))
            if w.get("engine"):
                cfg["backend"] = str(w["engine"])
            r = photo.generate(self.ws, str(w.get("prompt", "")), cfg,
                               size=int(w.get("size", 512) or 512))
            self.vars[st["id"]] = r
            return {"detail": r["name"]}, None
        if stype == "pixel":
            from nova_modules import pixelart
            r = pixelart.generate(self.ws, str(w.get("prompt", "")),
                                  size=int(w.get("size", 32) or 32),
                                  palette=str(w.get("palette", "") or "") or None,
                                  symmetry=str(w.get("symmetry", "") or "") or None,
                                  seed=str(w.get("seed", "") or "") or None,
                                  scale=int(w.get("scale", 8) or 8))
            self.vars[st["id"]] = {"path": r.get("path", ""), "name": r.get("name", "")}
            return {"detail": r.get("name", "")}, None
        if stype == "knowledge":
            from nova_modules import knowledge
            mode = str(w.get("mode", "search") or "search")
            q = str(w.get("query", "") or w.get("text", ""))
            if mode == "remember":
                from nova_modules import module_data_dir
                note_dir = module_data_dir(self.ws, "knowledge")
                # v6.5: unique name (two runs in the same second used to
                # overwrite each other) AND the note is ingested into the
                # knowledge store - before, it was written into a folder
                # nothing ever read, so "remember" remembered nothing.
                note = note_dir / ("note-%s-%s.md" % (
                    time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6]))
                note.write_text(str(w.get("text", ""))[:20_000], encoding="utf-8")
                detail = "note saved"
                try:
                    # v6.7 fix: the ABSOLUTE path failed knowledge's
                    # _safe_join on Windows (the ':' of 'C:\' is not in
                    # _PATH_SAFE) and on paths with '(' - the note was
                    # written but NEVER ingested. The workspace-relative
                    # path ingests everywhere.
                    rel = note.resolve().relative_to(
                        Path(self.ws).resolve()).as_posix()
                    ing = knowledge.ingest(self.ws, [rel])
                    detail = "note saved (searchable: %d chunks)" \
                             % int(ing.get("chunks", 0))
                except Exception:
                    pass          # the note file itself is safe either way
                self.vars[st["id"]] = {"text": "saved"}
                return {"detail": detail}, None
            hits = knowledge.search(self.ws, q, k=int(w.get("k", 4) or 4))
            packed = "\n---\n".join("[src: %s]\n%s" % (h["doc"], h["text"]) for h in hits)
            self.vars[st["id"]] = {"text": packed, "hits": hits}
            return {"detail": "%d hits" % len(hits)}, None
        if stype == "http":
            return self._http(st, w)
        if stype == "condition":
            return self._condition(w)
        if stype == "transform":
            text = str(w.get("text", ""))
            self.vars[st["id"]] = {"text": text}
            return {"detail": text[:200]}, None
        if stype == "delay":
            secs = min(max(float(w.get("seconds", 1) or 1), 0.0), MAX_DELAY)
            time.sleep(secs)
            return {"detail": "waited %.1fs" % secs}, None
        raise ModuleError("unhandled step type '%s'" % stype)

    def _crew(self, st, w):
        """Roles -> each answers the task -> synthesis turn. The roles
        field is a single string of role descriptions (one per line) or
        'name: goal' lines - kept simple and template-safe."""
        roles = [r.strip() for r in str(w.get("roles", "")).splitlines() if r.strip()][:4]
        task = str(w.get("text", "") or w.get("task", ""))
        if not roles:
            roles = ["planner: break the task into concrete steps"]
        answers = []
        for role in roles:
            rname, _, goal = role.partition(":")
            out = self._chat()("You are %s on a small team. %s" %
                               (rname.strip() or "a teammate",
                                goal.strip() or "Do your part well."),
                               task)
            answers.append({"role": rname.strip() or role[:30], "text": out})
        synth = self._chat()("You are the lead. Merge the teammates' answers "
                             "into one clear, actionable reply.",
                             "\n\n".join("[%s]\n%s" % (a["role"], a["text"])
                                         for a in answers))
        self.vars[st["id"]] = {"text": synth, "answers": answers}
        return {"detail": "%d roles" % len(roles)}

    def _http(self, st, w):
        url = str(w.get("url", "")).strip()
        if not re.match(r"^https?://[^\s]+$", url) or len(url) > 800:
            raise ModuleError("http step needs a plain http(s) URL")
        # v6.8.1: the flow http node used to bypass the project's own
        # SSRF policy - a saved flow could hit 127.0.0.1 / LAN /
        # cloud-metadata IPs (reachable from the web face). nova_search's
        # safe_url applies the same private-network block as /search.
        try:
            import nova_search as _ns
            safe = _ns.safe_url(url)
            if safe is None:
                raise ModuleError("http step refused: private-network / "
                                  "unsafe URL is blocked")
            url = safe
        except ModuleError:
            raise
        except Exception:
            # v8.0: FAIL CLOSED - a broken nova_search import used to
            # silently downgrade the private-network block to the bare
            # scheme check, re-enabling 127.0.0.1 / LAN / metadata
            # fetches from a saved flow (the codebase's own threat model
            # includes half-initialized nova_* modules on disk).
            raise ModuleError("http step refused: the SSRF policy module "
                              "is unavailable")
        try:
            # v8.10.1 fix: plain urlopen re-resolves the hostname AFTER the
            # safe_url check - a TTL-0 DNS answer (public IP to the check,
            # 192.168.x.x to the fetch) walked past the SSRF guard
            # (DNS rebinding). http_get_bytes is the pinned stack the rest
            # of the project fetches through: every redirect re-checked,
            # the actual peer IP verified, read capped.
            import nova_search as _ns2
            raw, _ctype, _final = _ns2.http_get_bytes(
                url, timeout=15, max_bytes=MAX_HTTP_BODY)
        except (urllib.error.HTTPError, urllib.error.URLError,
                socket.timeout, TimeoutError, OSError, ValueError) as e:
            raise ModuleError("http step failed (%s)"
                              % str(getattr(e, "reason", e))[:120]) from None
        text = raw.decode("utf-8", "replace")
        data = None
        try:
            data = json.loads(text)
        except ValueError:
            pass
        out = {"text": text}
        if isinstance(data, (dict, list)):
            out["json"] = data
        self.vars[st["id"]] = out
        return {"detail": "%d bytes from %s" % (len(raw), urllib.parse.urlparse(url).netloc[:80])}, None

    def _condition(self, w):
        left = str(w.get("left", ""))
        right = str(w.get("right", ""))
        op = str(w.get("op", "not_empty")).lower()
        if op == "eq":
            ok = left == right
        elif op == "ne":
            ok = left != right
        elif op == "contains":
            ok = right.lower() in left.lower()
        elif op == "gt":
            ok = _num(left) > _num(right)
        elif op == "lt":
            ok = _num(left) < _num(right)
        elif op == "empty":
            ok = not left.strip()
        else:
            ok = bool(left.strip())
        goto = str(w.get("goto", "") or "").strip() or None
        if ok and goto:
            return {"detail": "true -> jump %s" % goto}, goto
        return {"detail": "true" if ok else "false (continue)",
                "status": "done" if ok else "skip"}, None

    def _code_context(self):
        try:
            import nova_repomap
            m = nova_repomap.build_style_map(self.ws, max_chars=1500)
            return str(m or "")
        except Exception:
            return ""


def _num(s):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------- public API
def run(ws, flow, inputs=None, chat_fn=None):
    """Synchronous run (CLI). Returns the final status dict."""
    norm = validate(flow)
    r = _Run(ws, norm, inputs, chat_fn)
    r.run()
    return _persist(ws, r)


def run_async(ws, flow, inputs=None, chat_fn=None):
    """Background run (web). Returns (run_id, status_dict)."""
    norm = validate(flow)
    run_id = uuid.uuid4().hex[:12]
    r = _Run(ws, norm, inputs, chat_fn)
    # v6.5: snapshot ONCE, before the thread starts, and return THAT - the
    # old re-snapshot after t.start() read r.vars while the worker was
    # mutating it (RuntimeError: dictionary changed size during iteration
    # on a fast first step -> the web caller lost the run_id with a 502).
    snap0 = _snapshot(r, run_id)
    _write_run(ws, run_id, snap0)

    def worker():
        # v6.2.1 fix: persist a snapshot after EVERY step so /api/flow_status
        # shows live progress; before, the initial 0-step snapshot was all
        # the web UI saw until the whole run was over.
        try:
            r.run(on_step=lambda: _write_run(ws, run_id, _snapshot(r, run_id)))
        except Exception as e:                     # must never kill the thread
            r.status = "failed"
            r.error = type(e).__name__ + ": " + str(e)[:200]
            r.finished = time.time()
        _persist(ws, r, run_id=run_id)
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return run_id, snap0


def _snapshot(r, run_id=None):
    return {"id": run_id or "", "name": r.flow["name"], "status": r.status,
            "error": r.error, "steps": r.log, "vars": _json_safe(r.vars),
            "started": r.started, "finished": getattr(r, "finished", 0)}


def _safe_value(v, depth=0):
    """JSON-serializable, size-capped view of one variable value."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        if isinstance(v, str) and len(v) > 2000:
            return v[:2000] + "..."
        return v
    if depth >= 3:
        return str(v)[:200]
    if isinstance(v, dict):
        return {str(k)[:60]: _safe_value(val, depth + 1)
                for k, val in list(v.items())[:40]}
    if isinstance(v, (list, tuple)):
        return [_safe_value(x, depth + 1) for x in list(v)[:60]]
    return str(v)[:200]


def _json_safe(vars_):
    return {k: _safe_value(v) for k, v in vars_.items()}


def _persist(ws, r, run_id=None):
    # v6.7 fix: the id must be allocated BEFORE the snapshot - the old
    # code wrote a uuid-named file whose payload carried "id": "", so
    # every CLI-era run was unreachable from the UI (run_status("")
    # fails ID_RE -> 404) and polling by the returned id was impossible.
    run_id = run_id or uuid.uuid4().hex[:12]
    snap = _snapshot(r, run_id)
    _write_run(ws, run_id, snap)
    return snap


def _run_mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _write_run(ws, run_id, snap):
    try:
        p = runs_dir(ws) / (str(run_id) + ".json")
        tmp = p.with_suffix(".json.part")
        tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(p)
        runs = sorted(runs_dir(ws).glob("*.json"), key=_run_mtime)
        if len(runs) > 60:
            for old in runs[:len(runs) - 60]:
                # v6.5: never delete the run file being written - uuid names
                # sort randomly, so the pruner could remove (and keep
                # removing on every write) the CURRENT run, 404-ing the UI
                # for the whole run and losing its result.
                # v6.7: prune by MTIME (oldest first) - sorting by uuid name
                # is random and could delete a live async run whenever the
                # folder crossed 60 files.
                if old.name == p.name:
                    continue
                try:
                    old.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def run_status(ws, run_id):
    run_id = str(run_id or "").strip()
    if not ID_RE.match(run_id):
        return None
    try:
        return json.loads((runs_dir(ws) / (run_id + ".json"))
                          .read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs(ws, cap=20):
    out = []
    def _mtime(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0   # pruned between glob and stat - just sort it last
    for p in sorted(runs_dir(ws).glob("*.json"), key=lambda x: -_mtime(x))[:cap]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": d.get("id", p.stem), "name": d.get("name", ""),
                        "status": d.get("status", "?"),
                        "steps_done": len(d.get("steps", [])),
                        "error": d.get("error", "")})
        except Exception:
            continue
    return out


SAMPLE = {
    "name": "idea-to-art",
    "steps": [
        {"id": "idea", "type": "prompt",
         "with": {"text": "یک ایده‌ی کوتاه برای یک صحنه‌ی شبانه بده (دو جمله)"}},
        {"id": "art", "type": "pixel",
         "with": {"prompt": "{{idea}}", "size": 32, "palette": "sunset"}},
        {"id": "tell", "type": "voice",
         "with": {"text": "پیکسل آرت آماده شد", "engine": "offline"}},
    ],
}
