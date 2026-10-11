"""Copy the CONTEXT's decisions, discretion and deferred sections verbatim into 06.4-RESEARCH.md (no retyping)."""
import pathlib
phase = pathlib.Path(__file__).resolve().parent.parent
ctx = (phase / "06.4-CONTEXT.md").read_text(encoding="utf-8").splitlines()
def between(start_marker, end_marker, include_start=True):
    s = next(i for i, l in enumerate(ctx) if l.startswith(start_marker))
    e = next(i for i, l in enumerate(ctx) if i > s and l.startswith(end_marker))
    return "\n".join(ctx[s + (0 if include_start else 1):e]).strip("\n")
decisions = between("## Implementation Decisions", "### Claude's Discretion")
discretion = between("### Claude's Discretion", "</decisions>", include_start=False)
deferred = between("<deferred>", "</deferred>", include_start=False).replace("## Deferred Ideas", "").strip("\n")
out = phase / "06.4-RESEARCH.md"
t = out.read_text(encoding="utf-8")
for key, val in (("@@DECISIONS@@", decisions), ("@@DISCRETION@@", discretion), ("@@DEFERRED@@", deferred)):
    assert key in t, key
    t = t.replace(key, val)
out.write_text(t, encoding="utf-8", newline="\n")
print("decisions lines", decisions.count("\n"), "discretion", discretion.count("\n"), "deferred", deferred.count("\n"))
