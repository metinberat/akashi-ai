# Agent instructions

**Read `AI_ENGINEERING_RULES.md` at the repository root before making changes.**
It is the single rule set shared by Codex, Claude and every other agent. This
file only points to it, so the two can never disagree.

The rules most often needed at a glance (the full text in
`AI_ENGINEERING_RULES.md` is authoritative):

1. Never commit to `main`; use `<agent>/<topic>` branches and separate Git
   worktrees for concurrent agents.
2. Keep IMPLEMENTED, VALIDATED, BENCHMARKED and LOCAL ACCEPTANCE REQUIRED
   distinct. Never invent results.
3. FORM (`products/form`) and AKASHI stay independently runnable; integrations
   are read-only adapters.
4. Cloud/external models are optional; local-first paths must keep working.
5. No secrets in the repository. Do not weaken security controls.

Useful entry points: `README.md`, `docs/architecture.md`, `docs/development.md`,
`docs/spatial-lab.md`, `docs/acceptance/spatial-lab-v1.md`.

`frontend/AGENTS.md` adds Next.js-specific notes for work inside `frontend/`.
