#!/usr/bin/env python3
# =====================================================================
#  Nova Code - file/module dependency graph (v6.8)
#
#  Understand big projects fast: imports become edges, cycles become
#  warnings, orphans become suspects. Outputs:
#    build(ws, rels)      graph dict {nodes, edges, missing, cycles}
#    text_report(graph)   terminal view
#    to_mermaid(graph)    paste into any markdown viewer
#    to_dot(graph)        graphviz dot file
#
#  Python: real ast Import/ImportFrom (relative imports resolved to the
#  local file when it exists). JS/TS: require('...') + import ... from.
#  Caps everywhere: MAX_FILES / MAX_EDGES keep a `node_modules`-scale
#  walk from eating RAM - the walk itself respects the ignore list.
# =====================================================================
import ast
import re
from pathlib import Path

MAX_FILES = 400
MAX_EDGES = 2000
MAX_NAME = 120

_JS_IMPORT = re.compile(
    r"""(?:require\(\s*['"]([^'"]{1,120})['"]\s*\))"""
    r"""|(?:import\s+[^'"]*?from\s+['"]([^'"]{1,120})['"])"""
    r"""|(?:import\s*\(\s*['"]([^'"]{1,120})['"]\s*\))""", re.M)

_DOT_SAFE = re.compile(r"[^A-Za-z0-9_]")


def _norm(rel):
    return Path(rel).as_posix() if rel else ""


def _module_to_rel(mod):
    """'pkg/sub/mod' -> 'pkg/sub/mod.py' (caller checks existence)."""
    return mod.replace(".", "/") + ".py"


def py_imports(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, TypeError):
        return [], []
    absolute, relative = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                absolute.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                names = [a.name for a in node.names]
                relative.append(("." * node.level, node.module or "", names))
            elif node.module:
                absolute.append(node.module)
    return absolute, relative


def js_imports(text):
    out = []
    for m in _JS_IMPORT.finditer(text):
        spec = m.group(1) or m.group(2) or m.group(3)
        if spec:
            out.append(spec)
    return out


def _resolve_js(spec, src_rel):
    """Relative spec -> workspace-relative file candidate(s)."""
    if not spec.startswith("."):
        return None
    base = Path(src_rel).parent
    target = (base / spec).as_posix()
    for cand in (target, target + ".js", target + ".ts",
                 target + "/index.js", target + "/index.ts"):
        yield cand


def build(ws, rels=None, max_files=MAX_FILES):
    """Scan the workspace (or an explicit file list) and return:
    {"nodes": {rel: {"lines": n, "kind": "py"|"js"|"other"}},
     "edges": [[src, dst], ...], "missing": [[src, spec], ...],
     "cycles": [[a, b, ...], ...]}"""
    ws = Path(ws)
    if rels is None:
        rels = []
        for p in ws.rglob("*"):
            if len(rels) >= max_files:
                break
            if not p.is_file():
                continue
            rel = p.relative_to(ws).as_posix()
            parts = set(rel.split("/"))
            if (".git" in parts or "node_modules" in parts
                    or ".nova" in parts or "__pycache__" in parts
                    or ".nova_backups" in parts or "venv" in parts
                    or ".venv" in parts):
                continue
            if p.suffix.lower() in (".py", ".js", ".ts", ".mjs", ".cjs",
                                    ".jsx", ".tsx"):
                rels.append(rel)
    rels = list(dict.fromkeys(rels))[:max_files]

    node_set = {}
    edges, missing = [], []
    relset = set(rels)
    for rel in rels:
        p = ws / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:400_000]
        except OSError:
            continue
        node_set[rel] = True
        ext = p.suffix.lower()
        if ext == ".py":
            absolute, relative = py_imports(text)
            # resolve relative imports: '.' = same package (src's dir)
            src_dir = Path(rel).parent
            for dots, mod, names in relative:
                up = len(dots) - 1
                base = src_dir
                ok = True
                for _ in range(up):
                    if base != Path("."):
                        base = base.parent
                    else:
                        ok = False
                        break
                if not ok:
                    continue
                # v6.8.1: `from . import x` has an EMPTY module part - the
                # old code built a junk candidate ('pkg.py' / '..py') and
                # the edge silently vanished. Try the named symbols and
                # the package __init__ instead.
                if mod:
                    cand = (base / _module_to_rel(mod)).as_posix()
                    if cand in relset:
                        edges.append([rel, cand])
                        continue
                    pkg_init = (base / mod.replace(".", "/") / "__init__.py").as_posix()
                    if pkg_init in relset:
                        edges.append([rel, pkg_init])
                        continue
                hit = False
                for a in names or ():
                    cand = (base / _module_to_rel(a)).as_posix()
                    if cand in relset:
                        edges.append([rel, cand])
                        hit = True
                pkg_init = (base / "__init__.py").as_posix()
                if not hit and pkg_init in relset:
                    edges.append([rel, pkg_init])
            for mod in absolute:
                cand = _module_to_rel(mod)
                if cand in relset:
                    edges.append([rel, cand])
                elif mod.split(".")[0] in {"os", "sys", "json", "re", "time",
                                           "math", "pathlib", "subprocess",
                                           "threading", "typing"}:
                    pass  # stdlib - not an edge, not "missing"
                else:
                    if len(missing) < 200:
                        missing.append([rel, mod[:MAX_NAME]])
        else:
            for spec in js_imports(text):
                if spec.startswith("."):
                    hit = next((c for c in _resolve_js(spec, rel)
                                if c in relset), None)
                    if hit:
                        edges.append([rel, hit])
                    elif len(missing) < 200:
                        missing.append([rel, spec[:MAX_NAME]])
        if len(edges) >= MAX_EDGES:
            edges = edges[:MAX_EDGES]
            break

    nodes = {}
    for rel in rels:
        nodes[rel] = {"lines": 0, "kind": "other"}
    for rel in node_set:
        nodes.setdefault(rel, {"lines": 0, "kind": "other"})
        nodes[rel]["kind"] = "py" if rel.endswith(".py") else "js"
    g = {"nodes": nodes, "edges": _dedupe(edges), "missing": missing,
         "cycles": find_cycles(nodes, edges)}
    return g


def _dedupe(edges):
    seen, out = set(), []
    for a, b in edges:
        if a == b:
            continue
        key = (a, b)
        if key not in seen:
            seen.add(key)
            out.append([a, b])
    return out


def find_cycles(nodes, edges):
    """Simple DFS back-edge collection; each cycle reported once."""
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
    color = {}          # 0 white 1 gray 2 black
    cycles = []

    def dfs(u, stack):
        color[u] = 1
        stack.append(u)
        for v in adj.get(u, ()):  # noqa
            c = color.get(v, 0)
            if c == 1:
                try:
                    i = stack.index(v)
                    cycles.append(stack[i:] + [v])
                except ValueError:
                    pass
            elif c == 0:
                dfs(v, stack)
        stack.pop()
        color[u] = 2

    for n in sorted(adj):
        if color.get(n, 0) == 0:
            dfs(n, [])
        if len(cycles) >= 20:
            break
    return cycles[:20]


def orphans(graph):
    """Nodes with no edges at all - dead candidates or entry points."""
    deg = {n: 0 for n in graph["nodes"]}
    for a, b in graph["edges"]:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    return sorted(n for n, d in deg.items() if d == 0)


def text_report(graph, max_rows=60):
    nodes, edges = graph["nodes"], graph["edges"]
    lines = [f"files: {len(nodes)}   edges: {len(edges)}"]
    indeg = {n: 0 for n in nodes}
    outdeg = {n: 0 for n in nodes}
    for a, b in edges:
        outdeg[a] = outdeg.get(a, 0) + 1
        indeg[b] = indeg.get(b, 0) + 1
    hub_rows = sorted(nodes, key=lambda n: -(indeg.get(n, 0) + outdeg.get(n, 0)))
    shown = 0
    for n in hub_rows:
        if not (indeg.get(n, 0) or outdeg.get(n, 0)):
            continue
        lines.append(f"  {n}  <- {indeg.get(n, 0)}  -> {outdeg.get(n, 0)}")
        shown += 1
        if shown >= max_rows:
            lines.append(f"  ... (+{len(hub_rows) - shown} more)")
            break
    if graph["cycles"]:
        lines.append(f"circular imports: {len(graph['cycles'])}")
        for c in graph["cycles"][:5]:
            lines.append("  CYCLE: " + " -> ".join(c))
    if graph["missing"]:
        lines.append(f"unresolved imports: {len(graph['missing'])} "
                     "(first few):")
        for src, spec in graph["missing"][:8]:
            lines.append(f"  {src} -> {spec}")
    orph = orphans(graph)
    if orph:
        lines.append(f"no imports in/out ({len(orph)}): " +
                     ", ".join(orph[:8]) + ("..." if len(orph) > 8 else ""))
    return "\n".join(lines)


def _mid(graph):
    """Sanitized node ids for mermaid/dot."""
    ids = {}
    for n in graph["nodes"]:
        ids[n] = _DOT_SAFE.sub("_", n.replace(".", "_").replace("/", "_"))[:40] \
            or "n" + str(len(ids))
    return ids


def to_mermaid(graph, max_edges=120):
    ids = _mid(graph)
    out = ["graph TD"]
    count = 0
    for a, b in graph["edges"]:
        if count >= max_edges:
            out.append(f"  %% (+{len(graph['edges']) - max_edges} more edges hidden)")
            break
        out.append(f"  {ids[a]}[\"{a}\"] --> {ids[b]}[\"{b}\"]")
        count += 1
    if not graph["edges"]:
        out.append("  EMPTY[\"no imports found\"]")
    return "\n".join(out)


def to_dot(graph, max_edges=400):
    ids = _mid(graph)
    out = ["digraph nova_deps {", '  rankdir="LR";',
           '  node [shape=box, fontsize=10];']
    count = 0
    for a, b in graph["edges"]:
        if count >= max_edges:
            out.append(f'  // (+{len(graph["edges"]) - max_edges} more edges hidden)')
            break
        out.append(f'  "{ids[a]}" [label="{a}"];')
        out.append(f'  "{ids[b]}" [label="{b}"];')
        out.append(f'  "{ids[a]}" -> "{ids[b]}";')
        count += 1
    out.append("}")
    return "\n".join(out)
