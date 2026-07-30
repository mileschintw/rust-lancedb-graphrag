# Agent Guidelines

## Language-Specific Rules

### Rust Guidelines
- **Trigger**: ONLY read or consult `rust-guidelines.md` when creating, editing, or refactoring Rust code (`.rs` files or Cargo components).
- **Action**: Before writing Rust code, view `rust-guidelines.md` in the root folder and adhere to its guidelines.
- **Scope Restriction**: Do NOT read `rust-guidelines.md` for non-Rust tasks (e.g., Go, HTML/JS, Protobuf, or documentation) to save context and prevent irrelevant rules from being applied.

### Go Guidelines
- **Trigger**: ONLY read or consult `go-guidelines.md` when creating, editing, or refactoring Go code (`.go` files or `go.mod`).
- **Action**: Before writing Go code, view `go-guidelines.md` in the root folder, detect the Go version from `go.mod` (using the pattern in the file), and adhere to its guidelines up to that Go version.
- **Scope Restriction**: Do NOT read `go-guidelines.md` for non-Go tasks (e.g., Rust, HTML/JS, Protobuf, or documentation) to save context and prevent irrelevant rules from being applied.

## Code Review Guidelines

### Claim/Lease Integration Tests (Review Convention)
- **Rule**: Every integration test that globally claims, leases, dequeues, or batch-selects mutable rows must use a unique per-test schema or isolated test database before queries run.
- **Reviewer Checklist**:
  - Verify every fixture and claimant connection uses the isolated per-test schema/database.
  - Verify every external snapshot before/after count query error is fatal (`t.Fatalf`) to prevent false-passing comparisons.
- **Note**: This is a review convention only; no automated linter, hook, or workflow policy is enforced.
