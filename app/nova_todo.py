#!/usr/bin/env python3
# =====================================================================
#  Nova Code - live task plan / checklist (v5.0)
#
#  For multi-step work the model outputs ONE plan block, then keeps it
#  updated in every later answer:
#
#      === PLAN ===
#      1. [x] create the project structure
#      2. [ ] write the parser
#      3. [ ] add tests
#      === END ===
#
#  nova.py parses it out of every answer, renders it live in the
#  terminal AND pushes it to the web UI as a {"t":"todo"} event, and the
#  auto/verify loops inject the current plan status into follow-up
#  prompts so a small model can not "forget" where it is. /todo manages
#  the list manually.
#
#  Parsing rules (deliberately forgiving - small models misformat):
#    - the LAST complete PLAN block in the text wins
#    - items: "1. text", "1) text", "- text", "* text"
#    - optional [x] / [X] = done, [ ] / missing = open
#    - a block with zero items is ignored (treated as no plan)
#  =====================================================================
import re

PLAN_OPEN_RE = re.compile(
    r"===\s*PLAN\s*===\s*\n(.*?)\n?\s*===\s*END(?:\s+PLAN)?\s*===",
    re.DOTALL | re.IGNORECASE)  # v7.14.1: small models emit lowercase
                                # "=== plan ===" - it used to be dropped
                                # by the case-sensitive regex while the
                                # pre-check above was case-INsensitive
ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[*\-+])\s*(?:\[(x|X|\s|)\]\s*)?(.+?)\s*$")
DONE_MARK_RE = re.compile(r"^\[(x|X)\]")


def parse_plan(answer):
    """Last PLAN block -> [{'done': bool, 'text': str}] ([] = no plan).
    Malformed blocks can never raise."""
    if not answer or "=== PLAN" not in answer.upper():
        return []
    items = []
    for m in PLAN_OPEN_RE.finditer(answer or ""):
        body = m.group(1) or ""
        cur = []
        for raw in body.splitlines():
            im = ITEM_RE.match(raw)
            if not im:
                continue
            mark, text = im.group(1), (im.group(2) or "").strip()
            if not text:
                continue
            # v6.5: a markdown separator ('---' / '***' / '**_') inside the
            # PLAN block used to become a bogus item ('--'), polluting
            # render()/progress() counts. Items must carry actual content.
            if not re.search(r"[\w\u0600-\u06FF]", text):
                continue
            done = bool(mark and mark.lower() == "x")
            cur.append({"done": done, "text": text[:160]})
        if cur:
            items = cur          # the LAST non-empty block wins
    return items


def merge_plan(old_items, new_items):
    """New non-empty plan replaces the old one; empty keeps the old."""
    return new_items if new_items else list(old_items or [])


def render(items):
    """'1. [x] done-item' lines for terminal / web rendering."""
    return "\n".join(f"{i}. [{'x' if it['done'] else ' '}] {it['text']}"
                     for i, it in enumerate(items or [], 1))


def progress(items):
    """'2/5' done string (or '' for an empty plan)."""
    n = len(items or [])
    if not n:
        return ""
    d = sum(1 for it in items if it["done"])
    return f"{d}/{n}"


def all_done(items):
    return bool(items) and all(it["done"] for it in items)


def status_prompt(items):
    """Injection for auto/verify follow-up turns: shows the model where
    the work stands and how to update the plan. '' when there is no
    plan. The WHOLE injection stays inside a small-window-safe cap."""
    if not items:
        return ""
    lines = render(items)
    if len(lines) > 500:
        lines = lines[:500]
    text = ("CURRENT TASK PLAN (keep it updated):\n" + lines + "\n"
            "When you answer, re-output the whole === PLAN === block with "
            "[x] marks for every step you finished and add new steps as "
            "needed - nothing else about the plan, just the block.\n")
    return text[:800]


def cmd_items_from_args(arg, items):
    """Manual /todo maintenance: returns (new_items, message).
    arg: '' show | 'done 2' | 'undone 2' | 'add text' | 'del 2' | 'clear'."""
    parts = (arg or "").strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    items = list(items or [])
    if sub in ("", "show", "list"):
        return (items, render(items) if items else "(no plan)")
    if sub == "clear" or sub == "reset":
        return ([], "plan cleared")
    if sub in ("add",):
        if not rest:
            return (items, "usage: /todo add <text>")
        items.append({"done": False, "text": rest[:160]})
        return (items, "added")
    if sub in ("done", "undone", "del", "rm"):
        if not rest.isdigit():
            return (items, f"usage: /todo {sub} <item number>")
        idx = int(rest) - 1
        if not (0 <= idx < len(items)):
            return (items, f"no item {rest} (plan has {len(items)})")
        if sub == "done":
            items[idx]["done"] = True
            return (items, f"marked done: {items[idx]['text']}")
        if sub == "undone":
            items[idx]["done"] = False
            return (items, f"reopened: {items[idx]['text']}")
        gone = items.pop(idx)
        return (items, f"deleted: {gone['text']}")
    return (items, "usage: /todo [show|add <t>|done <n>|undone <n>|del <n>|clear]")
