# AKASHI Windows Computer Agent

AKASHI's computer layer extends the loopback-authenticated Windows Agent. It
does not expose a shell and it does not accept executable paths from clients.

## Runtime loop

The Core runs one bounded action per cycle:

`OBSERVE → PLAN → ACT → OBSERVE/VERIFY → CONTINUE`

The observation combines real top-level window state with a one-shot,
compressed screenshot. A configured VISION model chooses one typed action from
the fixed schema. Screen pixels, file contents, web pages, and application text
are treated as untrusted data, not instructions.

Typed primitives cover:

- top-level window discovery and foreground state;
- focus, minimize, maximize, restore, move, and explicit close;
- bounded mouse, drag, scroll, Unicode typing, keys, and shortcuts;
- approved-root file search, UTF-8 reading, create, copy, move, and rename;
- existing allowlisted application/project launch, telemetry, screen and camera.

Every input result says only that input was sent. Semantic success is decided
from the next observation; the planner cannot promote an unverified input into
a completed task without looking again.

## Safety boundary

- Agent binds to loopback and requires its dedicated bearer token.
- Mouse/keyboard, window mutation, and file mutation are CONFIRM actions.
- Generic keyboard input into terminals is blocked. Development execution stays
  behind the existing pinned project-script registry.
- No delete primitive, arbitrary process path, generic shell, credential access,
  security-settings control, or hidden continuous capture exists.
- Consequential UI submissions stop for a dedicated confirmed workflow.
- Durable state contains window/action metadata only. Screenshots and file
  contents are never persisted by the computer-session store.

## API

`POST /computer/tasks` starts a protected bounded task. Set `approved: true`
only after the user has authorized desktop input/state changes. Sessions can be
inspected or cancelled under `/computer/tasks`.

Normal chat can select the same computer service for explicit multi-step
desktop imperatives. Desktop voice already calls the normal Core `/chat` path,
so it reaches this same action architecture rather than a second voice brain.

## MARK 57 reference review

MARK 57's dynamic action discovery, live-session continuity, and repeated
screen observation informed this design. Its broad PyAutoGUI surface, generic
development command execution, and action-success strings were deliberately
not adopted. No MARK 57 source was copied; AKASHI uses its existing registry,
security model, provider router, and native typed Windows implementation.
