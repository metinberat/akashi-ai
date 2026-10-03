# Character expertise V3 foundation

AKASHI retains V2 goal graphs and Windows Agent execution. V3 adds source analysis and expert memory; it does not confer professional artistic judgment.

## Source and ingestion

Authenticated `/expertise/characters` accepts the canonical JSON document and explicit provenance. `/expertise/characters/upload` accepts multipart `file` and JSON `provenance`. Supported sources are canonical JSON, OBJ, glTF 2.0 with embedded base64 buffers, and GLB. No external asset was downloaded. Synthetic fixtures are explicitly labeled.

Example provenance: `{"reference":"local:user-supplied-character-v1","category":"asset_observation","synthetic":false,"version":"1","license":"user-supplied"}`. For generated tests use `category=synthetic_fixture` and `synthetic=true`.

The parser never fetches URLs or opens referenced local files. glTF external buffers remain unavailable. Draco, meshopt and sparse accessors fail explicitly. Upload bodies are also subject to the backend's existing HTTP body limit; parser maximum is 32 MiB, detailed geometry 200,000 vertices, decoded accessors 2 million scalar samples. Use metadata-only exports for larger scenes. These budgets bound local analysis, not just transport.

`.blend` sources use the fixed Windows Agent `blender_operation` with `operation=inspect_character`, an approved `.blend` path and a new approved `.json` output path. Source scripts are disabled using `--disable-autoexec`; existing output files are not overwritten. The JSON is then uploaded. Direct FBX parsing and FBX import are not implemented. Export FBX to GLB/canonical JSON with the source application first.

## Canonical representation

`app/expertise/schema.py` preserves original joint names, parent IDs, source transforms, bind matrices, mesh positions/faces, skin weights, materials, object hierarchy and animation channels. glTF and Blender retain source coordinate systems and transform spaces; they are not silently converted to a common unit/rest pose. Semantic mappings add inferred anatomical region, joint, side and role. Unknown names remain unknown. Raw source bytes remain content-addressed for exact provenance.

Analyzers separate observed presence/counts, computed topology/skin/hierarchy/animation metrics and name-derived inference. Connected components include isolated vertices. Skin metrics include unweighted/unnormalized vertices, influence histogram, sparsity and joint coverage. Animation curves are stored where available; root motion and looping remain `not_evaluated`. UV/material/texture references are inspected, not decoded or rendered. Face-control names do not establish facial behavior. Deformation quality is not inferred from bone names.

## Expert memory and validation

SQLite stores compact asset, knowledge and experience records with WAL transactions and indexes. Source blobs live separately under `character_sources/<sha256>`; equal bytes share one blob. Cache identity includes hash, provenance and parser/analyzer revision. Ingestion is atomic at the database-record level and safe to retry; unfinished ingestion has no partially analyzed record. Full multi-stage resumable analysis is not yet necessary/implemented for these bounded parsers.

Knowledge has `observed_fact`, `computed_metric`, `inferred_principle` or `hypothesis` type, confidence, source hash/asset ID, method, validation history and synthetic scope. `/expertise/knowledge/{id}/validate` requires an authenticated user attestation with evidence reference and method. A linked task must be completed. This is not automatic proof of artistic quality. Synthetic validation remains `synthetic_only`.

V2 knowledge retrieval includes current expert records from SQLite. Retrieved text remains untrusted evidence. General notes retain category, claimed authority, confidence and version. Source claims do not acquire execution privileges or approve themselves. Active skills, not unreviewed candidates, enter the planner context.

Task experiences capture goal, context, retrieved knowledge, plan revisions, execution/evaluation, corrections, failures and terminal outcome. Successful and failed paths remain distinct. Experiences are checkpointed after subgoals and on shutdown/finalization. No screenshot/audio binary is stored by this layer.

## API and comparison

- `GET /expertise/characters` — compact summaries.
- `GET /expertise/characters/{id}` — source provenance, canonical data and analysis.
- `POST /expertise/compare` — semantic set/count and hierarchy/skin comparisons; no topology equality assumption or quality ranking.
- `GET /expertise/knowledge?query=forearm%20twist` — source-traceable findings.
- `GET /expertise/experiences` — execution/evaluation learning records.
- `GET /expertise/dataset` — dataset preparation; defaults exclude synthetic and unvalidated data.

Explicit `include_synthetic=true&validated_only=false` exports fabricated development examples. Name mappings are labeled heuristic and never ground truth. Default validated export excludes those mappings; skin samples require validation of the corresponding skin metrics. Source weights are observed targets, not a certification of optimal weights. Source digest is the split group to prevent train/test source leakage. Dataset export is bounded to 200,000 sampled vertices; no model training is performed.

The Autonomy Hub exposes compact character inventory and expertise retrieval without changing desktop/mobile presentation.

## Validation and next asset

Tests generate A–G fixtures: basic humanoid, finger chains, twist/toe chains, different names, missing facial/animation data, alternative hierarchy and malformed cyclic input. A short local Blender test generates a synthetic scene, inspects it through the fixed adapter, exports GLB and ingests both formats.

For the first real asset, supply a user-owned GLB with embedded resources, or canonical JSON from `inspect_character`. Preserve license/source/version metadata. Run inspection and verify anatomical mappings before treating them as reusable production knowledge. Actual deformation, render/visual quality, topology suitability and rig-control behavior still require supervised task/visual evaluations.
