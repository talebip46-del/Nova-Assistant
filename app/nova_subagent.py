#!/usr/bin/env python3
# =====================================================================
#  Nova Code - parallel sub-agents on the LOCAL brain (v6.8)
#
#  Independent sub-tasks run CONCURRENTLY: Ollama happily serves
#  several /api/chat streams at once (CPU-inference interleaves them,
#  multiple GPUs/MIG or llama.cpp parallel slots really run them
#  side by side). This module:
#    split_tasks()  one utility call turns a goal into an ordered JSON
#                   list of independent sub-tasks (validated, capped)
#    run_parallel() ThreadPool over worker functions, results in ORDER,
#                   per-task error captured, never raises
#    merge_report() one final utility call fuses the sub-results
#
#  Safety: sub-agents NEVER write files or run commands in v6.8 - they
#  return text (analysis / proposals / code snippets) that the MAIN
#  session presents or applies through the normal review path.
#  Concurrency default: min(3, cores//2), env NOVA_AGENTS, hard cap 6.
# =====================================================================
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

MAX_TASKS = 6
MAX_RESULT_CHARS = 8000
# v7.1.0: bracket-soup hardening - a derailed model (or a prompt-injected
# goal) used to freeze the whole /agent turn: every '[' x ']' pair was a
# json.loads attempt, O(B^2) (600+600 brackets = 7 s, 4000+4000 > 2 min).
MAX_SPLIT_ANSWER_CHARS = 20000
MAX_SPLIT_ATTEMPTS = 200

_SPLIT_INSTR = (
    "You are a task planner. Split the GOAL below into independent "
    "sub-tasks that different helpers could research or draft at the same "
    "time WITHOUT talking to each other (no ordering dependencies like "
    "'after step 1'). Answer with ONLY a JSON array of short strings, "
    "2 to %d items, no markdown, no numbering, no commentary.\n\nGOAL: " % MAX_TASKS)


def parse_task_list(text):
    """Extract a JSON string array from a model answer. v6.8.1: the old
    single greedy regex spanning from the FIRST '[' to the LAST ']' in
    the whole answer - any other bracketed text ('[1] for details',
    '[see below]') around the real list made json.loads fail and the
    whole task list was lost. Now: every bracket candidate is tried, the
    first that parses as a JSON array of strings wins.
    v7.1.0: the answer is capped, only candidates that even LOOK like a
    JSON array ('[' followed by a quote or '[') are parsed, and the scan
    stops after a fixed attempt budget - bracket soup can no longer hang
    the turn."""
    if not text:
        return []
    text = text[:MAX_SPLIT_ANSWER_CHARS]
    attempts = 0
    for m in re.finditer(r"\[", text):
        start = m.start()
        # v8.0: the char AFTER '[' used to have to be a quote/bracket
        # literally - pretty-printed JSON arrays ('[\n  "task",') were
        # all rejected and split_tasks() silently returned []. Whitespace
        # between '[' and the first element is normal model output.
        if not re.match(r"[\s]*(?:[\"\']|\[)", text[start + 1:]):
            continue                  # cannot open a JSON array of strings
        # try successively longer closes from this '['
        for close in re.finditer(r"\]", text[start + 1:]):
            attempts += 1
            if attempts > MAX_SPLIT_ATTEMPTS:
                return []             # budget gone - refuse, never hang
            end = start + 1 + close.end()
            try:
                data = json.loads(text[start:end])
            except (ValueError, TypeError):
                continue
            if isinstance(data, list):
                out = []
                for item in data[:MAX_TASKS]:
                    if isinstance(item, str) and item.strip():
                        t = " ".join(item.split())[:300]
                        if t:
                            out.append(t)
                if out:
                    return out
    return []


def split_tasks(goal, chat_fn, section="utility"):
    """chat_fn(prompt, section) -> answer text. Returns the sub-task
    strings ([] when the model would not cooperate)."""
    answer = chat_fn(_SPLIT_INSTR + str(goal or "")[:4000], section)
    return parse_task_list(answer)


def run_parallel(tasks, worker, max_parallel=None):
    """Run worker(task) for every task concurrently. Returns
    [(task, result_or_None, err_or_None)] IN INPUT ORDER. worker must be
    thread-safe (the chat layer's global state is read-only per call)."""
    tasks = [t for t in tasks if t][:MAX_TASKS]
    if not tasks:
        return []
    if max_parallel is None:
        try:
            cpus = os.cpu_count() or 2
        except Exception:
            cpus = 2
        # v6.8.1: NOVA_AGENTS=abc used to raise ValueError out of
        # run_parallel (docstring promises it never raises)
        # v8.10.1: NOVA_AGENTS=1 used to yield 2 workers (the max(2, ...)
        # floor overrode the env) - the documented 'env NOVA_AGENTS, hard
        # cap 6' contract now honors 1 (= the serial path below).
        try:
            env_n = int(os.environ.get("NOVA_AGENTS", "0") or 0)
        except (ValueError, TypeError):
            env_n = 0
        max_parallel = min(6, max(1, env_n)
                           if env_n else min(3, max(1, cpus // 2)))
    max_parallel = max(1, min(int(max_parallel), MAX_TASKS))
    results = [None] * len(tasks)

    def _one(i, t):
        try:
            results[i] = (t, worker(t), None)
        except Exception as e:
            results[i] = (t, None, str(e)[:300])

    if max_parallel <= 1 or len(tasks) == 1:
        for i, t in enumerate(tasks):
            _one(i, t)
    else:
        # v7.1.0: NO `with` block. ThreadPoolExecutor.__exit__ calls
        # shutdown(wait=True), which JOINED the workers on the way out -
        # so the v6.9 Ctrl+C fix (cancel + wait=False) was defeated by
        # the very context manager it ran inside: Ctrl+C during a long
        # generation still froze the REPL for minutes. Explicit executor,
        # never join on exit.
        ex = ThreadPoolExecutor(max_workers=max_parallel)
        futs = [ex.submit(_one, i, t) for i, t in enumerate(tasks)]
        try:
            for f in futs:
                f.result()
        except KeyboardInterrupt:
            # Cancel what is queued; running threads finish in the
            # background while the REPL regains control immediately.
            for f in futs:
                f.cancel()
            raise
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    # ThreadPoolExecutor keeps submission order in results by index, but
    # filter out any hole defensively (worker raised in submit itself)
    return [r for r in results if r is not None]


def merge_report(goal, task_results, chat_fn, section="utility"):
    """One final call fusing the sub-results into a plan of record."""
    blocks = []
    for i, (task, res, err) in enumerate(task_results, 1):
        body = (res or "")[:MAX_RESULT_CHARS]
        if err:
            body = f"(sub-agent failed: {err})"
        blocks.append(f"--- sub-task {i}: {task} ---\n{body or '(empty)'}")
    prompt = (
        "These are the outputs of independent helpers for the same goal. "
        "Merge them into ONE coherent answer: what to build/change (with "
        "exact file names), conflicts resolved in favor of the more "
        "specific output, then the single best next step. Plain text.\n\n"
        "GOAL: " + str(goal or "")[:2000] + "\n\n" + "\n\n".join(blocks))
    return chat_fn(prompt, section)


def concurrency_note(max_parallel):
    return (f"ran {max_parallel} sub-agent(s) in parallel - every sub-agent "
            "only DRAFTS text; the main session applies anything real")
