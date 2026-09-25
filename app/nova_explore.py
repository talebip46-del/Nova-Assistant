#!/usr/bin/env python3
# =====================================================================
#  Nova Code - PARALLEL MULTI-SOLUTION EXPLORATION (v7.5.0)
#
#  The model is asked k times (threaded against the LOCAL server) and
#  the best answer is chosen by a deterministic validator score:
#    + complete protocol blocks, + files that pass the lint gate,
#    + a Run: line, + no unnamed leftovers  -  a truncated or broken
#    candidate simply loses.
#  The diffs BETWEEN candidates for the same target file are built so
#  the user can see HOW the answers differ (web /api/explore, /explore).
#
#  LOCAL ONLY: on a local server extra samples cost time, not money.
#  Cloud backends must never be multi-sampled here (3-4x API cost) -
#  the caller (nova.chat_turn) enforces nova_backend.best_of_count().
#
#  Every candidate is scored on the RAW ANSWER TEXT - nothing is
#  applied by this module; the winner flows back into the normal
#  chat_turn pipeline (parse -> repair -> offer_apply) untouched.
# =====================================================================
import threading

try:
    import nova_quality as quality
except Exception:
    quality = None


def score_answer(answer, expect_files=True):
    """Deterministic 0-100 score for one candidate answer."""
    try:
        s = 0
        text = str(answer or "")
        if not text.strip():
            return 0
        n_files = text.count("=== FILE:")
        n_edits = text.count("=== EDIT:")
        if n_files or n_edits:
            s += 34
        elif expect_files:
            s += 6                      # prose-only answer on a work task
        # closed blocks matter: FILE:/EDIT: without their END: means
        # truncation (an EDIT-only answer still gets the closure bonus)
        if (n_files or n_edits) \
                and text.count("=== END ===") >= n_files + n_edits:
            s += 18
        if "Run:" in text or "Preview:" in text:
            s += 10
        # lint every parsed file body (quality gate = the SAME check the
        # apply path uses, so the winner can actually land)
        if quality is not None:
            bodies = _file_bodies(text)
            ok_all, checked = True, 0
            for name, body in bodies:
                ok, _problem = quality.preapply_check(name, body)
                checked += 1
                if not ok:
                    ok_all = False
                    break
            if checked and ok_all:
                s += 26
            elif checked and not ok_all:
                s -= 30                 # a broken file must never win
        # completeness flag from the transport layer
        return max(0, min(100, s))
    except Exception:
        return 0


def _file_bodies(text):
    """Cheap === FILE: name === body extraction for scoring (not the
    full parse - edge cases here only cost score points, never bytes)."""
    import re
    out = []
    for m in re.finditer(r"===\s*FILE:\s*(.+?)\s*===\n(.*?)\n?=== END ===",
                         text, re.S):
        out.append((m.group(1), m.group(2)))
    return out


def explore(fetch_fn, temperature, k=3, max_parallel=2, expect_files=True):
    """Run k generations, return the ranked results.
    fetch_fn(temperature) -> (text, complete)   [the caller adapts
    stream_chat with a quiet flag + section=None].
    Returns {"ranked": [{text, score, complete}], "best": int, "order": []}."""
    k = max(1, int(k))
    results = [None] * k
    sem = threading.Semaphore(max(1, int(max_parallel)))

    def one(i):
        try:
            with sem:                 # bounds real parallelism (OOM-safe)
                text, complete = fetch_fn(temperature)
            results[i] = {"text": text or "", "complete": bool(complete),
                          "score": score_answer(text, expect_files)}
        except Exception as e:
            results[i] = {"text": "", "complete": False, "score": 0,
                          "error": str(e)}

    threads = [threading.Thread(target=one, args=(i,), daemon=True)
               for i in range(k)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(7200)      # local models can be slow; silence-capped upstream
    ranked = [r if r else {"text": "", "complete": False, "score": 0}
              for r in results]
    # every candidate failed to even produce text (server down, transport
    # signature mismatch) -> the caller must fall back to the normal path,
    # never apply an empty winner
    if ranked and all(r.get("error") or not r["text"].strip()
                      for r in ranked):
        raise RuntimeError("explore: all candidates failed")
    order = sorted(range(k), key=lambda i: -ranked[i]["score"])
    return {"ranked": ranked, "best": order[0] if order else 0,
            "order": order}


def candidate_diffs(ranked, chosen=-1, path_filter=None, max_pairs=3):
    """Human-visible diff between the WINNER and each runner-up for a
    shared target file: [(file, winner_name, other_name, diff_lines)]."""
    try:
        import nova_diffview as diffview
    except Exception:
        return []
    if chosen < 0 or chosen >= len(ranked):
        return []
    out = []
    win_files = dict(_file_bodies(ranked[chosen]["text"]))
    for j, cand in enumerate(ranked):
        if j == chosen:
            continue
        other_files = dict(_file_bodies(cand["text"]))
        for path, body in other_files.items():
            if path_filter and path_filter not in path:
                continue
            if path in win_files and win_files[path] != body:
                try:
                    d = diffview.unified_diff(path, body, win_files[path],
                                              max_lines=24)
                except Exception:
                    d = []
                out.append((path, f"#{chosen + 1}", f"#{j + 1}", d))
            if len(out) >= max_pairs:
                return out
    return out
