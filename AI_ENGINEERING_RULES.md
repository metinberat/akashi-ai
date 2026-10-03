# AI engineering rules (shared by Claude, Codex and any other agent)

This file is the **single** rule set for every AI agent working in this
repository. `CLAUDE.md` and `AGENTS.md` only point here. If a rule needs to
change, change it here, in one commit, with the reason in the message. Do not
create a second, diverging copy of these rules anywhere else.

Directory-scoped files (for example `frontend/AGENTS.md`, which carries the
Next.js-version notice written by `next dev`) add tool-specific facts. They never
override this file.

## 1. The repository is the source of truth

- Read the relevant code, tests and docs before a significant change. Prompts,
  tickets and memory can be stale; the repository decides.
- When the code and a document disagree, trust the code, then fix the document
  or record the difference.
- Before any change that crosses a subsystem boundary, read the subsystem's
  docs in `docs/` and its tests.

## 2. Branches and isolation

- No agent commits to `main`. Work on a branch named `<agent>/<topic>` (for
  example `claude/spatial-lab-v1-current`, `codex/spatial-lab-local-acceptance`).
- Never merge, force-push or rewrite history on `main` or on someone else's
  branch. The owner reviews and merges.
- When two agents work at the same time on one machine, each uses its own Git
  worktree (`git worktree add ../akashi-<topic> <branch>`). Do not share one
  working directory.
- A handoff between agents is a pushed branch plus a document that states what
  was done, what was validated and what remains (see `docs/acceptance/`).

## 3. Preserve working capability

- Do not break an existing capability to add a new one. Run the affected test
  suites before and after the change and compare.
- Prefer additive, bounded changes. Do not rewrite working architecture to make
  it look like a plan or a prompt.
- If a defect in existing code blocks the work, fix it only when the fix is
  clearly correct and small; otherwise document it and stop widening scope.
- Do not weaken a security, permission or approval control to make a feature
  easier. If a control must change, narrow the change to the exact capability,
  test it, and document it in `docs/security.md`.

## 4. Honest status: implemented ≠ validated ≠ benchmarked

Use these words exactly:

| Word | Meaning |
| --- | --- |
| IMPLEMENTED | Code exists and is wired in. |
| VALIDATED | An automated or manual check exercised it and passed. Say which check and on what environment. |
| BENCHMARKED | Measured against a stated threshold on stated hardware, with the numbers recorded. |
| LOCAL ACCEPTANCE REQUIRED | Needs the owner's physical machine (camera, GPU, Windows, Blender GUI, microphone, local models). |

- Never claim a physical, hardware, visual or performance result you did not
  observe. A mock test is not a hardware test. One successful run is not
  reliability.
- Never invent numbers. If a threshold cannot be chosen without the physical
  machine, write `LOCAL ACCEPTANCE REQUIRED`.
- Report failing tests with their output. Report skipped steps as skipped.
- Pre-existing environment-specific test failures (for example Windows-only
  DPAPI tests on Linux) are listed as such, not hidden and not "fixed" by
  deleting or skipping tests.

## 5. Local-first and optional cloud

- AKASHI and FORM must keep their fundamental operation with no cloud model or
  external API. External models are optional quality accelerators unless a
  document explicitly says otherwise.
- New features need a deterministic local path (rules, numeric methods, local
  models) and must degrade with a clear status when an optional provider is
  missing.
- No secrets, tokens, API keys or credentials in source, tests, fixtures,
  documentation or commits.

## 6. Module boundaries

- **FORM is a separate product** (`products/form`). It must keep running without
  AKASHI Core, and AKASHI must keep running without FORM. Integrations read
  FORM's data through explicit, read-only, versioned adapters; they never write
  FORM's database and never mutate FORM artifacts.
- Do not create a second registry for something another module already owns
  (FORM projects/versions, AKASHI tools, tasks, events).
- AI orchestration stays in FastAPI Core. Clients render and collect input;
  they do not hold provider credentials.

## 7. Reuse before reinvention

- Before writing a subsystem, ask whether AKASHI or FORM already has one or
  will obviously need one. Extend or generalise it when reuse is clear; do not
  build speculative abstractions for imagined futures.
- Shared foundations currently available:
  - `backend/app/history/` — canonical digests, JSON patches, hash-chained
    append-only action log, undo/redo, deterministic replay verification.
  - `backend/app/tools/` — typed tool registry with `safe`/`confirm`/`restricted` risk.
  - `backend/app/live/` — natural-language action registry for `/chat`.
  - `backend/app/events/hub.py` — redacted, process-local event fan-out.
  - `frontend/src/lib/spatial/gesture/` — renderer-independent hand-gesture engine.
- Duplicated logic across the Python/TypeScript boundary needs a contract test
  (see `shared/contracts/`).

## 8. Destructive operations

- Deleting user data, overwriting artifacts, resetting stores, force-pushing
  and similar irreversible actions need an explicit request or confirmation.
- Commands that remove user-visible state from a scene or project carry a
  `confirm` risk level and must be confirmable and undoable where feasible.
- Corrupted persisted state fails closed with a clear message; it is never
  silently "repaired" into a different state.

## 9. Evidence for "working"

- A claim that something works names the test, command or observation that
  shows it, the environment it ran in, and the date.
- Tests must check real logic. Do not write tests that only assert that a mock
  returned what it was told to return.
- Performance claims need instrumentation output, not impressions.

## 10. Roadmap awareness

- Read the relevant roadmap/acceptance documents before major work and keep
  future directions possible (for example real depth, WebXR, remote devices for
  Spatial Lab) without implementing them early.
- When you leave work unfinished, leave the next concrete step written down.
