# Agent Guidelines

## Language guidelines

Before writing code in one of these languages, read its guideline file:

- **Rust** (`.rs` files, Cargo components): `rust-guidelines.md`.
- **Go** (`.go` files, `go.mod`): `go-guidelines.md`. A plain read leaves the version command at its top unexecuted,
  so run that command yourself and target the Go version it prints.

## Planning archive

`.planning/` and `.discussion/` are the v1.0 build record. Look there for the reasoning behind a `D-NN` decision ID
cited in code or config, or for a past evaluation run. Treat both as **read-only**: the README and `docs/` link into
them.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`mileschintw/rust-lancedb-graphrag`, via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

None: issues get no labels, even when a skill names one. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Multi-session work

Multi-session work: records in the worktree on branch coord (find it with git worktree list; never merged); the coordinator runs /relay:coordinate, workers follow relay:work.
