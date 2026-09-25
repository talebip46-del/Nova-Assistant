#!/usr/bin/env python3
# =====================================================================
#  Nova Assistant - multi-module CLI (v8.12.0)
#
#    python3 nova_assistant.py                  -> the coding agent (nova.py)
#    python3 nova_assistant.py voice <text>     -> text-to-speech
#    python3 nova_assistant.py stt <file>       -> speech-to-text
#    python3 nova_assistant.py photo <prompt>   -> image generation
#    python3 nova_assistant.py pixel <prompt>   -> offline pixel art
#    python3 nova_assistant.py flow <list|show|run|del> [name]
#    python3 nova_assistant.py knowledge <ingest|search|stats|reset> [...]
#    python3 nova_assistant.py models           -> EVERY brain in one table
#    python3 nova_assistant.py platforms <list|scan|add name url|del name>
#    python3 nova_assistant.py assign <module> <backend> [key=value ...]
#    python3 nova_assistant.py serve [port]     -> the web dashboard
#
#  Everything unknown falls through to nova.py's main(), so this file
#  is a SUPERSET entry point - the old commands all keep working.
# =====================================================================
import argparse
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

MODULE_WORDS = {"voice", "stt", "photo", "pixel", "flow", "knowledge",
                "models", "platforms", "assign"}


def _ws():
    """Workspace root (same default as nova.py: ./nova-workspace).
    v6.2.1 fix: the old argv scan for --workspace was DEAD CODE - argparse
    rejected the flag before _ws() ever ran ('unrecognized arguments').
    Every subparser now registers --workspace (shared parent parser), so
    `nova_assistant.py voice hi --workspace X` really writes into X.
    v6.5 fix: the --workspace=X form was accepted by argparse but silently
    ignored here - both spellings work now."""
    for i, a in enumerate(sys.argv):
        if a == "--workspace" and i + 1 < len(sys.argv):
            val = sys.argv[i + 1].strip()
            if val:
                return Path(val).expanduser().resolve()
        elif a.startswith("--workspace="):
            # v6.5 fix: the = form was accepted by argparse but silently
            # ignored here (and the old [:-1] scan even missed it when it
            # was the LAST argument) - both spellings work everywhere now.
            val = a.split("=", 1)[1].strip()
            if val:
                return Path(val).expanduser().resolve()
    return Path(os.environ.get("NOVA_WORKSPACE", "")
                or "nova-workspace").expanduser().resolve()


def _err(msg, code=2):
    print("  [!] " + msg)
    sys.exit(code)


def _kv_args(pairs):
    """['k=v', ...] -> dict (strings only, tiny caps)."""
    out = {}
    for p in pairs or []:
        k, _, v = str(p).partition("=")
        k = k.strip()
        if k and len(k) <= 40:
            out[k] = v[:1000]
    return out


# --------------------------------------------------------------- commands
def cmd_voice(args):
    from nova_modules import voice, assign
    text = " ".join(args.text).strip()
    if not text:
        _err("usage: nova_assistant.py voice <text to speak>")
    cfg = assign.resolve(_ws(), "voice")
    r = voice.synthesize(_ws(), text, cfg, want_engine=args.engine or None)
    print("  Nova Voice  [%s]  %s  (%d bytes)" % (r["engine"], r["path"], r["bytes"]))
    if r.get("note"):
        print("      " + r["note"])


def cmd_stt(args):
    from nova_modules import voice, assign
    p = Path(args.file).expanduser()
    if not p.is_file():
        _err("audio file not found: " + str(p))
    if p.stat().st_size > voice.MAX_AUDIO:
        _err("audio file too large (12 MB max)")
    cfg = assign.resolve(_ws(), "voice")
    if not cfg.get("url"):
        cfg["url"] = os.environ.get("NOVA_STT_URL", "http://127.0.0.1:8080/v1")
    text = voice.transcribe(_ws(), p.read_bytes(), cfg, filename=p.name)
    print("  Nova Voice STT: " + (text[:2000] or "(empty)"))


def cmd_photo(args):
    from nova_modules import photo, assign
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        _err('usage: nova_assistant.py photo "prompt"')
    cfg = dict(assign.resolve(_ws(), "photo"))
    if args.engine:
        cfg["backend"] = args.engine
    r = photo.generate(_ws(), prompt, cfg, size=args.size)
    print("  Nova Photo  [%s]  %s  (%d bytes)" % (r["engine"], r["path"], r["bytes"]))
    if r.get("note"):
        print("      " + r["note"])


def cmd_pixel(args):
    from nova_modules import pixelart
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        _err('usage: nova_assistant.py pixel "prompt" [--size 32 --palette pico8]')
    r = pixelart.generate(_ws(), prompt, size=args.size, palette=args.palette,
                          seed=args.seed or None, scale=args.scale)
    print("  Nova PixelArt  [%s/%dx%d@%dx]  %s" %
          (r["plan"]["palette"], r["size"], r["size"], r["scale"], r["path"]))


def cmd_flow(args):
    from nova_modules import flow
    ws = _ws()
    action = args.action or "list"
    if action == "list":
        items = flow.list_flows(ws)
        if not items:
            print("  no saved flows yet - the web UI has a one-click sample")
            return
        print("  %-24s %-4s %s" % ("NAME", "STEPS", "TYPES"))
        for f in items:
            print("  %-24s %-4d %s" % (f["name"], f["steps"], ",".join(f["types"])))
        return
    if action == "show":
        f = flow.get(ws, args.name or "")
        _err("flow not found") if f is None else print(
            json.dumps(f, ensure_ascii=False, indent=1))
        return
    if action == "run":
        f = flow.get(ws, args.name or "")
        if f is None:
            _err("flow not found: " + str(args.name))
        print("  running '%s' ... (LLM steps may take a while)" % f["name"])
        snap = flow.run(ws, f, inputs=_kv_args(args.inputs))
        for s in snap["steps"]:
            mark = {"done": "+", "skip": "~", "failed": "x"}.get(s["status"], "?")
            print("   [%s] %-12s %-10s %s" % (mark, s["id"], s["type"],
                                              s["detail"][:80]))
        print("  status: %s%s" % (snap["status"],
                                  (" - " + snap["error"]) if snap["error"] else ""))
        # v6.7: a failed flow used to exit 0 - `novacode flow run deploy
        # && next_step` proceeded after a failed deploy.
        if snap.get("status") == "failed":
            sys.exit(1)
        return
    if action == "del":
        print("  deleted" if flow.delete(ws, args.name or "") else "  not found")
        return
    _err("unknown flow action '%s' (list|show|run|del)" % action)


def cmd_knowledge(args):
    from nova_modules import knowledge
    ws = _ws()
    action = args.action or "stats"
    if action == "ingest":
        if not args.paths:
            _err("usage: knowledge ingest <path> [<path> ...]")
        r = knowledge.ingest(ws, args.paths)
        print("  ingested %d file(s) -> %d new chunks (%d total)%s" %
              (r["files"], r["chunks"], r["total_chunks"],
               ("; skipped: " + ", ".join(r["skipped"][:5])) if r["skipped"] else ""))
        return
    if action == "search":
        hits = knowledge.search(ws, " ".join(args.paths or []), k=8)
        if not hits:
            print("  no hits (ingest some files first)")
            return
        for h in hits:
            print("  %.3f  %s" % (h["score"], h["doc"]))
            print("        " + h["text"][:140].replace("\n", " "))
        return
    if action == "stats":
        print("  docs: %(docs)d  chunks: %(chunks)d" % knowledge.stats(ws))
        return
    if action == "reset":
        print("  removed %d index file(s)" % knowledge.reset(ws)["removed"])
        return
    _err("unknown knowledge action")


def cmd_models(args):
    """One table: Ollama + model FILES + platforms + cloud."""
    import nova_models as nmodels
    import nova_localmodels as lmodels
    import nova_providers as providers
    import nova_platforms as platforms
    ws = _ws()
    print("  Ollama models:")
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                    timeout=4) as resp:
            tags = json.loads(resp.read(4_000_000).decode("utf-8", "replace"))
        rows = nmodels.table_rows(nmodels.parse_tags(tags))
        if not rows:
            print("    (none installed yet - ollama pull <model>)")
        for i, name, size, desc in rows:
            print("    %-3d %-42s %-9s %s" % (i, name[:42], size, desc))
    except Exception:
        print("    (Ollama is not reachable)")
    if lmodels is not None:
        try:
            dirs = lmodels.model_dirs(ws)
            entries = lmodels.scan_dirs(dirs)
        except Exception:
            entries = []
        runnable = [e for e in entries if e.get("runnable")]
        print("  Model files: %d runnable" % len(runnable))
        for e in runnable[:10]:
            cat = e.get("category", "general")
            print("    file:%-44s %-9s %s%s" %
                  (e["name"][:44], nmodels.fmt_size(e.get("size")),
                   e.get("arch", ""),
                   (" [" + cat + "]") if cat != "general" else ""))
        voices = [e for e in entries if e.get("format") == "onnx"]
        if voices:
            print("  Voice models (.onnx for Piper): %d" % len(voices))
            for e in voices[:10]:
                print("    file:%s" % e["name"])
        print("  categories: local/ = general · local/code · local/voice"
              " · local/photo (Flow sees all)")
    print("  Platforms:")
    found = False
    for r in platforms.scan(ws, timeout=2.0):
        mark = "ok " if r["ok"] else "-- "
        print("    [%s] %-10s %-34s %s" % (mark, r["name"], r["base"][:34],
                                           ("models: " + str(len(r["models"])))
                                           if r["ok"] else r["note"]))
        found = True
    if not found:
        print("    (none configured - see: platforms add)")
    print("  Cloud providers: " + ", ".join(providers.names()))


def cmd_platforms(args):
    import nova_platforms as platforms
    ws = _ws()
    action = args.action or "list"
    if action == "list":
        for p in platforms.all_platforms(ws):
            print("  %-12s %s" % (p["name"], p["base"]))
        if not platforms.all_platforms(ws):
            print("  (none configured; presets: localai shimmy lmstudio vllm"
                  " llamacpp ollama-openai koboldcpp tgwebui jan gpt4all)")
        return
    if action == "scan":
        print("  probing platforms ...")
        for r in platforms.scan(ws, include_presets=True):
            print("  [%s] %-10s %-34s %s" %
                  ("ok " if r["ok"] else "-- ", r["name"], r["base"][:34],
                   ("%d models, e.g. %s" % (len(r["models"]),
                                            r["models"][0][:30]))
                    if (r["ok"] and r["models"]) else r["note"]))
        return
    if action == "add":
        if not args.extra or len(args.extra) < 1:
            _err("usage: platforms add <name> <base-url>")
        name = args.extra[0]
        base = args.extra[1] if len(args.extra) > 1 else ""
        cur = platforms.load_config(ws)
        cur.append({"name": name, "base": base})
        saved = platforms.save_config(ws, cur)
        print("  saved %d platform(s)" % len(saved))
        return
    if action == "del":
        cur = platforms.load_config(ws)
        new = [p for p in cur if p["name"] != (args.name or "")]
        platforms.save_config(ws, new)
        print("  %d platform(s) remain" % len(new))
        return
    _err("unknown platforms action")


def cmd_assign(args):
    from nova_modules import assign as A
    ws = _ws()
    if not args.module:
        for row in A.assignments_view(ws):
            if not row["assignable"]:
                continue
            cfg = row["cfg"]
            print("  %-10s -> %s" % (row["id"], json.dumps(cfg, ensure_ascii=False)))
        return
    module = args.module
    if not args.backend:
        _err("usage: assign <module> <backend> [model=.. url=.. voice=.. path=..]")
    cfg = {"backend": args.backend}
    cfg.update(_kv_args(args.extra))
    saved = A.save_module(ws, module, cfg)
    print("  assigned %s -> %s" % (module, json.dumps(saved, ensure_ascii=False)))


def cmd_serve(args):
    import nova  # noqa: E402
    argv = ["--web"] + (["--port", str(args.port)] if args.port else [])
    if args.host:
        argv += ["--host", args.host]
    # v6.5: --workspace was parsed and then DISCARDED - the dashboard came
    # up on the default ./nova-workspace with no warning.
    if getattr(args, "workspace", ""):
        argv += ["--workspace", str(args.workspace)]
    elif os.environ.get("NOVA_WORKSPACE", ""):
        argv += ["--workspace", os.environ["NOVA_WORKSPACE"]]
    sys.argv = [sys.argv[0]] + argv
    nova.main()


# --------------------------------------------------------------- parser
def build_parser():
    p = argparse.ArgumentParser(
        prog="nova_assistant",
        description="Nova Assistant v8.12.0 - the multi-module local AI toolbox")
    # shared parent: --workspace works on EVERY module command (v6.2.1 fix,
    # see _ws()) - one parser, added via parents= so the flag is never
    # rejected by argparse again
    wsp = argparse.ArgumentParser(add_help=False)
    wsp.add_argument("--workspace", default="",
                     help="workspace root (default: ./nova-workspace or $NOVA_WORKSPACE)")
    sub = p.add_subparsers(dest="module")

    v = sub.add_parser("voice", help="text-to-speech", parents=[wsp])
    v.add_argument("text", nargs="*")
    v.add_argument("--engine", default="")
    v.set_defaults(fn=cmd_voice)

    s = sub.add_parser("stt", help="speech-to-text (needs an STT server)", parents=[wsp])
    s.add_argument("file")
    s.set_defaults(fn=cmd_stt)

    ph = sub.add_parser("photo", help="image generation", parents=[wsp])
    ph.add_argument("prompt", nargs="*")
    ph.add_argument("--engine", default="")
    ph.add_argument("--size", type=int, default=512)
    ph.set_defaults(fn=cmd_photo)

    px = sub.add_parser("pixel", help="offline pixel art", parents=[wsp])
    px.add_argument("prompt", nargs="*")
    px.add_argument("--size", type=int, default=32)
    px.add_argument("--palette", default="")
    px.add_argument("--seed", default="")
    px.add_argument("--scale", type=int, default=8)
    px.set_defaults(fn=cmd_pixel)

    f = sub.add_parser("flow", help="workflow engine (the integration hub)", parents=[wsp])
    f.add_argument("action", nargs="?", default="list")
    f.add_argument("name", nargs="?", default="")
    f.add_argument("--inputs", nargs="*", default=[])
    f.set_defaults(fn=cmd_flow)

    k = sub.add_parser("knowledge", help="local document brain", parents=[wsp])
    k.add_argument("action", nargs="?", default="stats")
    k.add_argument("paths", nargs="*", default=[])
    k.set_defaults(fn=cmd_knowledge)

    m = sub.add_parser("models", help="list EVERY brain: ollama/files/platforms/cloud",
                       parents=[wsp])
    m.set_defaults(fn=cmd_models)

    pl = sub.add_parser("platforms", help="OpenAI-compatible platform registry",
                        parents=[wsp])
    pl.add_argument("action", nargs="?", default="list")
    pl.add_argument("name", nargs="?", default="")
    pl.add_argument("extra", nargs="*", default=[])
    pl.set_defaults(fn=cmd_platforms)

    a = sub.add_parser("assign", help="give ONE module its OWN brain", parents=[wsp])
    a.add_argument("module", nargs="?", default="")
    a.add_argument("backend", nargs="?", default="")
    a.add_argument("extra", nargs="*", default=[])
    a.set_defaults(fn=cmd_assign)

    sv = sub.add_parser("serve", help="the web dashboard (all modules)", parents=[wsp])
    sv.add_argument("--port", type=int, default=0)
    sv.add_argument("--host", default="")
    sv.set_defaults(fn=cmd_serve)
    return p


def main():
    argv = sys.argv[1:]
    # no args / agent-looking args -> the classic coding agent
    first = argv[0] if argv else ""
    if not argv or first.startswith("-") or first not in MODULE_WORDS | {"serve"}:
        import nova
        nova.main()
        return
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.fn(args)
    except KeyboardInterrupt:
        print("\nBye!")
    except Exception as e:
        msg = str(e).strip() or type(e).__name__
        _err(msg, 1)


if __name__ == "__main__":
    main()
