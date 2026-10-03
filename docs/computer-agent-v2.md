# AKASHI Computer Agent V2

V2 extends the V1 typed Windows action boundary; it does not replace it.

## Execution model

`GOAL → GRAPH PLAN → EXECUTE → OBSERVE → EVALUATE → REPLAN → CHECKPOINT`

- `app.autonomy.engine.LongHorizonTaskEngine` owns durable goals and dependency graphs.
- Each subgoal declares an outcome, channel, dependencies, and observable acceptance criteria.
- The V1 computer agent remains the verified desktop/vision fallback.
- Browser work prefers the loopback-only CDP semantic adapter, then may fall back to V1 vision/input.
- Restarted in-flight nodes become pending with an interrupted outcome; they are never marked successful.

## Channels

- Browser: isolated AKASHI Chromium profile, DOM + accessibility snapshots, semantic actions.
- Filesystem/development: approved-root typed operations and pinned project scripts.
- Professional applications: typed adapters when available; Blender currently supports scene inspection, current-scene render, and glTF export without arbitrary Python execution.
- Desktop/vision: V1 screen observation and Windows input when no stronger structured interface exists.

## Memory and learning

- Task checkpoints retain subgoals, attempts, evaluations, artifacts, entities, and bounded observable events.
- Screenshots, audio, credentials, raw model payloads, and private file contents are not stored in task history.
- Completed tasks produce candidate workflow skills. Candidates require explicit activation before being treated as established skills.
- The knowledge store is a local lexical retrieval foundation. All retrieved content is marked untrusted and cannot authorize actions.

## Safety

- No generic shell, arbitrary browser JavaScript, arbitrary Blender Python, or credential extraction.
- Browser debugging binds to loopback and uses a dedicated profile.
- Consequential submit/send/pay/delete goals remain blocked pending a dedicated confirmation workflow.
- Browser and Windows state changes require approved tasks.
