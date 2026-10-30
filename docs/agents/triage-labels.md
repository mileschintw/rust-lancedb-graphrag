# Triage labels

This repo uses no triage labels. The `triage` skill is not installed, and none of the default labels (`needs-triage`,
`needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) exist on GitHub.

When a skill says to apply a triage label (for example `to-spec` or `to-tickets` applying `ready-for-agent`), create
the issue without `--label`. An issue counts as ready once it is open. Relay schedules lanes from blocked-by links
alone and never reads labels.
