#!/usr/bin/env python3
# =====================================================================
#  Nova Code - "Council" mode: two brains, one question (v5.0)
#
#  /council <question> streams the SAME question through the ACTIVE
#  provider AND a partner (a second provider, or simply a second local
#  Ollama model), shows both answers, and can ask the active brain for
#  a final JUDGE round: compare both, name the stronger points and bugs
#  of each, merge into one best answer.
#
#  Partner spec (via /council with <spec>):
#      ollama            the local brain again (rarely useful)
#      groq              provider name - its default model
#      openai:gpt-4o-mini  provider + explicit model
#      qwen2.5-coder:7b  a second installed Ollama model
#  Default partner when nothing is configured: the first cloud provider
#  whose API key is actually set; if none, another installed Ollama
#  model (the biggest that is not the current one).
#
#  Zero deps, no threads fighting over stdout: answers are collected
#  sequentially (slow-hardware patience preserved) and the caller
#  decides how to display them (terminal headers / web side columns).
# =====================================================================
import json
import urllib.error
import urllib.request

PARTNER_FILE = "council.json"      # .nova/council.json

try:
    import nova_atomic as natom
except Exception:
    natom = None
MAX_ANSWER_CHARS = 12_000


def load_partner(ws):
    try:
        from pathlib import Path
        from nova_policy import NOVA_DIR
        p = Path(ws) / NOVA_DIR / PARTNER_FILE
        if p.is_file():
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(obj, dict) and obj.get("spec"):
                return str(obj["spec"])[:80]
    except Exception:
        pass
    return ""


def save_partner(ws, spec):
    try:
        from pathlib import Path
        from nova_policy import NOVA_DIR
        p = Path(ws) / NOVA_DIR / PARTNER_FILE
        # v6.7: unique scratch name (cross-process tmp collision)
        if natom is not None:
            return natom.write_text_atomic(
                p, json.dumps({"spec": str(spec)[:80]}, ensure_ascii=False))
        import os
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"spec": str(spec)[:80]}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, p)
        return ""
    except OSError as e:
        return str(e)


def _local_kind(name, providers_mod):
    """True for local-server providers (never a council partner pick)."""
    try:
        e = providers_mod.entry(name) or {}
        return e.get("kind") in ("ollama", "lmstudio", "llamacpp", "vllm") \
            or bool(e.get("local"))
    except Exception:
        return False


def resolve_partner(spec, active_name, active_model, providers_mod, ollama_models=None):
    """spec -> (provider_name, model, label) or raises ValueError with a
    short English message. `ollama_models` = installed local model names
    (optional; improves 'another local model' defaults).
    v6.7 fix: default-partner detection used to check ENV keys only -
    vault keys (the v6.6 default store) were invisible, so /council fell
    through to a local model although /key groq ... was set. Custom
    providers were unknown to this function entirely (a saved spec
    'myrelay/qwen' was mistaken for an Ollama model name -> 404)."""
    spec = str(spec or "").strip()
    if not spec:
        # default: first cloud/custom provider with a key, else another
        # local model
        if providers_mod is not None:
            for name in providers_mod.names():
                if name == active_name or _local_kind(name, providers_mod):
                    continue
                try:
                    has_key, _masked = providers_mod.key_status(name)
                except Exception:
                    has_key = False
                if not has_key:
                    continue
                try:
                    cfg = providers_mod.resolve(name)
                except Exception:
                    continue        # unresolved (no model) - skip quietly
                model = cfg.get("model") or ""
                if not model:
                    ent = providers_mod.entry(name) or {}
                    model = ent.get("model") or ""
                if not model:
                    continue
                label = cfg.get("label") or name
                return (name, model, f"{label} ({model})")
        models = [m for m in (ollama_models or [])
                  if m and m.split(":")[0] != str(active_model).split(":")[0]]
        if models:
            pick = max(models, key=len)     # biggest name = usually biggest model
            return ("ollama", pick, f"Ollama ({pick})")
        raise ValueError("no partner available: set a cloud API key or install "
                         "a second Ollama model, or use: /council with <provider>")
    if ":" in spec:
        prov, model = spec.split(":", 1)
        prov, model = prov.strip().lower(), model.strip()
    else:
        prov, model = spec.lower(), ""
    if providers_mod is not None:
        # v7.9 audit fix: canonize the alias ('b.ai' -> 'bai') so the
        # usage ledger keeps ONE per-provider row for the platform and
        # the known/resolve checks below see the canonical entry.
        prov = providers_mod._canon(prov)
        known = prov in providers_mod.PROVIDERS \
            or providers_mod.entry(prov) is not None     # v6.7: customs too
        if known:
            try:
                cfg = providers_mod.resolve(prov)
            except Exception:
                # a missing key must not block CONFIGURING a partner - the
                # clean ProviderError surfaces when the call is actually made
                info = providers_mod.PROVIDERS.get(prov) or {}
                cfg = {"label": info.get("label", prov), "model": info.get("model", "")}
            if not model and not cfg.get("model"):
                ent = providers_mod.entry(prov) or {}
                model = ent.get("model") or ""
            model = model or cfg.get("model") or ""
            return (prov, model, f"{cfg.get('label', prov)} ({model})")
    # unknown provider name: treat as a local Ollama model name
    return ("ollama", spec, f"Ollama ({spec})")


def os_environ_get(key):
    import os
    return (os.environ.get(key) or "").strip()


def collect_ollama(model, messages, temperature, timeout, ollama_url):
    """Non-streaming Ollama call -> full answer text (or raise)."""
    payload = {"model": model, "messages": messages, "stream": False,
               "options": {"temperature": temperature}}
    req = urllib.request.Request(
        ollama_url + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # v6.2.1 fix: cap the read like every other reader in the project -
        # a runaway response must not balloon the process memory
        data = json.loads(resp.read(4_000_000).decode("utf-8", "replace"))
    msg = data.get("message") or {}
    text = msg.get("content", "") if isinstance(msg, dict) else ""
    usage = {"prompt_tokens": data.get("prompt_eval_count") or 0,
             "completion_tokens": data.get("eval_count") or 0,
             "actual": True}
    return (str(text)[:MAX_ANSWER_CHARS], usage)


def collect_provider(cfg, model, messages, temperature, timeout, providers_mod):
    """Collect one full answer from any cloud provider -> (text, usage
    {'prompt_tokens','completion_tokens','actual':bool}).

    v7.9 audit fix: the usage dict is now PASSED INTO stream_chunks so
    the REAL prompt/completion counts the provider reports reach the
    cost ledger - the old hardcoded {0, 0, False} booked every council
    round as a FREE turn on the usage panel."""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "actual": False}
    parts = []
    for piece in providers_mod.stream_chunks(cfg, model, messages,
                                             temperature, timeout=timeout,
                                             usage=usage):
        parts.append(piece)
        if sum(len(p) for p in parts) > MAX_ANSWER_CHARS:
            break
    text = "".join(parts)[:MAX_ANSWER_CHARS]
    return (text, usage)


def judge_prompt(question, answer_a, answer_b, label_a, label_b):
    """The judge round prompt - active brain merges the two answers."""
    return (
        "You are the judge of a council of two AI assistants. Both answered "
        "the SAME request. Compare them, name concretely what each got right "
        "and where each is wrong or incomplete, then produce ONE merged best "
        "answer that keeps the strengths of both and fixes their mistakes. "
        "Keep any code complete and runnable.\n\n"
        f"## Request\n{question}\n\n"
        f"## Answer A ({label_a})\n{answer_a[:6000]}\n\n"
        f"## Answer B ({label_b})\n{answer_b[:6000]}\n\n"
        "## Your output\nStart with a one-line verdict "
        "(A stronger / B stronger / tie + why), then the merged answer.")
