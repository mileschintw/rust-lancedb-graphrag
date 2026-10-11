"""Diff the re-scored copy against the committed run: report.json, metadata.json, report.md (D-200)."""
import json, sys, pathlib, difflib
a = pathlib.Path(sys.argv[1]); b = pathlib.Path(sys.argv[2])  # committed, copy

def walk(x, y, path=""):
    out = []
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x: out.append((path + "/" + k, "<absent>", repr(y[k])[:120]))
            elif k not in y: out.append((path + "/" + k, repr(x[k])[:120], "<absent>"))
            else: out += walk(x[k], y[k], path + "/" + k)
    elif isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y): out.append((path, f"len={len(x)}", f"len={len(y)}"))
        for i, (p, q) in enumerate(zip(x, y)): out += walk(p, q, f"{path}[{i}]")
    elif x != y:
        out.append((path, repr(x)[:120], repr(y)[:120]))
    return out

for name in ("report.json", "metadata.json"):
    ja = json.loads((a / name).read_text(encoding="utf-8")); jb = json.loads((b / name).read_text(encoding="utf-8"))
    d = walk(ja, jb)
    print(f"== {name}: {len(d)} differing leaf values")
    for p, x, y in d[:60]: print(f"  {p}\n     committed: {x}\n     copy     : {y}")
for name in ("report.md",):
    ta = (a / name).read_text(encoding="utf-8").splitlines(); tb = (b / name).read_text(encoding="utf-8").splitlines()
    d = [l for l in difflib.unified_diff(ta, tb, "committed", "copy", lineterm="", n=0)]
    print(f"== {name}: {len(d)} diff lines")
    for l in d[:40]: print("  " + l[:200])
# byte-equality of other files
for f in sorted(p.name for p in a.iterdir() if p.is_file()):
    if (b / f).exists():
        same = (a / f).read_bytes() == (b / f).read_bytes()
        print(f"bytes-equal {f}: {same}")
    else: print(f"missing in copy: {f}")
for f in sorted(p.name for p in b.iterdir() if p.is_file() and not (a / p.name).exists()): print(f"NEW in copy: {f}")
