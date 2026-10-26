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
