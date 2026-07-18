# Possible External Agent Host (Later)

An external runtime may eventually combine Agent Workflow method/Artifacts, Agent Bus transport,
and AI Memory knowledge. This repository does not currently define an Agent Host architecture,
Plugin SDK, provider interface, scheduler, or process-management contract.

The `scripts/` directory remains a dogfood operations surface for discovering real runtime needs.
Do not migrate or generalize it until repeated downstream use proves which behaviors belong in an
external runtime and which, if any, should become supported Agent Workflow conveniences.
