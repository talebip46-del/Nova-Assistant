#!/usr/bin/env python3
# =====================================================================
#  Nova Code - the BACKEND-AWARE policy layer (v7.5.0)
#
#  The rule the product now follows:
#    every capability whose goal is to COMPENSATE FOR A WEAK MODEL
#    (multi-sample generation, idiom templates, condensed prompts,
#     speculative drafts...) is locked to LOCAL brains.
#    every capability whose goal is to GUARANTEE CORRECT OUTPUT
#    (lint/AST gate, parse-retry rounds, atomic writes...) stays on
#    for EVERY backend - local or cloud frontier.
#    Cloud brains see their rich, full prompt: helper layers must never
#    limit a strong model's abilities, and must never silently multiply
#    the API bill (3-4x cost for best-of-N is local-only economics).
#
#  The backend of the CODING section is whoever actually serves it:
#  /brain coding route first (.nova/providers.json), else the active
#  provider - the same resolution the session already uses.
#
#  Everything here is deterministic, pure stdlib and fail-soft: an
#  error or a missing module must never break a chat turn.
# =====================================================================
import os

LOCAL_KINDS = ("ollama", "?", "lmstudio", "llamacpp", "vllm")

# features that compensate for model weakness -> LOCAL ONLY by default
WEAKNESS_FEATURES = ("best_of", "idiom_strict", "speculative", "explore")
# features that only guarantee correctness -> ALWAYS on (pinned by tests)
CORRECTNESS_FEATURES = ("lint", "parse_retry", "atomic_write")


def classify_kind(cfg):
    """'local' | 'cloud' from one provider config dict (fail-soft)."""
    try:
        kind = str((cfg or {}).get("kind", "ollama")).lower()
    except Exception:
        kind = "ollama"
    return "local" if kind in LOCAL_KINDS else "cloud"


def prompt_profile(backend):
    """The two prompt profiles the user asked for:
    local_small    - condensed, imperative, few-shot examples, firm idioms
    cloud_frontier - the rich full prompt, idioms only as OPTIONAL hints"""
    return "local_small" if backend == "local" else "cloud_frontier"


def feature_enabled(feature, backend):
    """Gate one feature for one backend, with env kill switches:
    NOVA_NO_<FEATURE>=1     -> off everywhere (user opt-out)
    NOVA_CLOUD_<FEATURE>=1  -> opt IN for cloud (explicit only, never default)
    Correctness features (lint / parse_retry / atomic_write) are ALWAYS on."""
    if feature in CORRECTNESS_FEATURES:
        return True
    if backend == "local":
        return os.environ.get("NOVA_NO_" + feature.upper(), "") != "1"
    if os.environ.get("NOVA_NO_" + feature.upper(), "") == "1":
        return False
    # cloud: OFF unless explicitly opted in
    return os.environ.get("NOVA_CLOUD_" + feature.upper(), "") == "1"


def best_of_count(backend):
    """Multi-sample generation size. Local models are free -> a small
    best-of-N is just time. Cloud APIs bill per request -> 1 answer
    unless NOVA_CLOUD_BEST_OF explicitly says otherwise."""
    if backend != "local":
        return 1
    try:
        n = int(os.environ.get("NOVA_BEST_OF", "3"))
    except ValueError:
        n = 3
    return max(1, min(int(n), 4))
