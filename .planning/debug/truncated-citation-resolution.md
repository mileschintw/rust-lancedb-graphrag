---
status: investigating
trigger: "T-06-15-03 / backstop must_have — citation naming a retrieved-but-truncated block"
created: 2026-08-22T20:26:00.000Z
updated: 2026-08-22T20:26:00.000Z
---

## Current Focus

hypothesis: "Citation resolution and marker extraction validate against the full ctx.evidence_blocks rather than the packed prompt subset, allowing citations to truncated blocks to resolve and ship excerpts."
test: "Inspect openrouter.rs, assemble_prompt.rs, and generate.rs evidence block propagation and citation resolution"
expecting: "Known-ID universe should be restricted to packed prompt subset; truncated citations must be treated as unresolvable and dropped."
next_action: "Update UAT and plan gap closure"

## Symptoms

expected: "A citation naming a retrieved-but-truncated block must not resolve or ship an excerpt; known-ID universe is the packed subset, treating truncated citations as unresolvable/dropped."
actual: "Today citations to truncated blocks resolve against ctx.evidence_blocks and excerpts are shipped via resolve_citations."
errors: "None reported (unexpected resolution of truncated citations)"
reproduction: "Construct retrieval result where block [N] is truncated out of the prompt by allowed_evidence_tokens, model emits [N] as citation."
started: "Phase 6"

## Evidence

- timestamp: 2026-08-22T20:26:00.000Z
  checked: "engine/src/generation/openrouter.rs:534"
  found: "pack_openrouter_messages returns _validation_evidence which is discarded"
  implication: "The adapter and downstream nodes validate and resolve against the full un-truncated evidence list when packed subset is not explicitly used."
- timestamp: 2026-08-22T20:26:00.000Z
  checked: "engine/src/workflow/nodes/generate.rs:188, 288-294"
  found: "evidence_ids is built from ctx.evidence_blocks; resolve_citations resolves against ctx.evidence_blocks"
  implication: "If ctx.evidence_blocks contains pre-truncated blocks or if packed subset isn't enforced as the ID universe, truncated blocks resolve successfully instead of dropping."

## Resolution

root_cause: "Citation marker resolution and structured citation extraction in GenerateNode and OpenRouter adapter operate against the full evidence blocks rather than the packed prompt subset, causing markers for truncated blocks to resolve and ship excerpts instead of being marked as unresolvable (Resolution::Dropped)."
fix: "Ensure the known-ID universe for marker resolution and citation resolution is restricted to the packed prompt subset. Treat citations referencing retrieved-but-truncated blocks as unresolvable (CITATION_DROPPED), and if all citations drop, apply the allow_model_only rule."
verification: "Add test where evidence set exceeds budget, truncated block is cited by model, verifying citation is dropped and no excerpt is shipped."
files_changed:
  - "engine/src/workflow/nodes/generate.rs"
  - "engine/src/generation/openrouter.rs"
