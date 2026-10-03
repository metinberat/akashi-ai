# V2 completion and acceptance boundaries

Persistent goal graphs orchestrate existing Computer Agent V1 and semantic CDP browser subgoals. The engine serializes desktop ownership, checks DAG labels/dependencies, transfers retry corrections, rewires failed dependencies to recovery leaves, continues after final-rejection replans, checkpoints graceful cancellation and exports structured experience. Restart never invents in-flight success.

Backend-configured reasoning providers have bounded retries and optional Ollama fallback (`AKASHI_AUTONOMY_LOCAL_FALLBACK=true`); mock cannot replace inference. Browser navigation bootstrap runs once so SPA redirects and link traversal can progress. Fuzzy semantic recovery requires an unambiguous high-confidence candidate; explicit selectors are preserved. Failed browser actions produce observations for the next plan. Browser page readiness alone no longer passes goal evaluation.

Only explicitly activated skills enter planning. RAG text remains untrusted data. Autonomy Hub has explicit task approval, resume and cancellation. V3 expertise/experience integrates with this same engine.

Start a goal through authenticated `POST /autonomy/tasks` with `{goal, session_id, approved}`. Approval authorizes the bounded task scope; consequential submissions remain restricted by existing action policies. Inspect `GET /autonomy/tasks/{id}`; use `/resume` after checking the current environment and `/cancel` to stop. Current external task execution must be verified by the user before declaring broad professional autonomy.

Limitations: no full-human long-horizon acceptance is claimed. Plans remain dependent on model quality/latency. DOM failures use bounded recovery; the V1 vision/UI channel remains available as a separately planned subgoal, not an automatic arbitrary browser script escape. Browser uploads/downloads and richer application adapters require further work. V3 doesn't implement Maya/Adobe automation or independent artistic judgment. One process supervises local runtime; multiple backend replicas are not supported as concurrent desktop owners.
