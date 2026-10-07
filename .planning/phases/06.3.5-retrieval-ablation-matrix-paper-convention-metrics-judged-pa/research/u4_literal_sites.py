"""U4 research snippet: classify every prost struct-literal site of QueryRagRequest / RetrievalSnapshot.

For each `Name {` occurrence under engine/ (excluding the generated src/pb tree), brace-match the literal and
report whether it ends with a `..` struct-update spread (then a new proto field needs NO edit) or lists every
field (then it must name the new field or the crate stops compiling). Type declarations, impl blocks, fn
signatures and return types are skipped. Read-only. Run from the repo root: python <this file>
"""
import re
from pathlib import Path

NAMES = ("QueryRagRequest", "RetrievalSnapshot")
total = {n: [0, 0, 0] for n in NAMES}  # literals, spread, must-edit
for path in sorted(Path("engine").rglob("*.rs")):
    posix = path.as_posix()
    if "/src/pb/" in posix:
        continue
    text = path.read_text(encoding="utf-8")
    for name in NAMES:
        for m in re.finditer(r"(?<![A-Za-z_])" + name + r"\s*\{", text):
            line = text.count("\n", 0, m.start()) + 1
            line_start = text.rfind("\n", 0, m.start()) + 1
            before = text[line_start : m.start()]
            if re.search(r"\b(struct|impl|enum|fn|for)\b", before) or "->" in before:
                continue
            depth, i = 0, m.end() - 1
            while i < len(text):
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                if depth == 0:
                    break
                i += 1
            body = text[m.end() : i]
            if re.match(r"^\s*(//.*)?\s*$", body):
                continue
            spread = bool(re.search(r"(^|\s)\.\.[A-Za-z_]", body))
            total[name][0] += 1
            total[name][1 if spread else 2] += 1
            print(f"{name:16s} {posix}:{line:<5d} {'spread (no edit)' if spread else 'LISTS ALL FIELDS (edit)'}")
print()
for n, (a, s, e) in total.items():
    print(f"{n}: literals={a} spread={s} must-edit={e}")
