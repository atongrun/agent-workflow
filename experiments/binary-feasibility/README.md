# Binary feasibility experiment

This directory is a CI-only research surface, not a production packaging ABI. `awf_entry.py`
exposes one private runtime probe before delegating normal arguments to the existing `awf` CLI.
`main.go` is a dependency-free launcher prototype that accepts only a sibling, basename-only app
whose SHA-256 matches `release.json`.

The experiment must not install or start native services, connect to a remote Agent Bus, invoke a
model, persist credentials, or repair a failed packaging candidate by changing production code.
Candidate artifacts and evidence are temporary GitHub Actions outputs.
