# Real FORM character fixture

`form-atelier-hud-seed57.glb` is genuine FORM output content, produced on
2026-10-04 by `backend/scripts/form_spatial_probe.py`:

- FORM production geometry: `construct(Design(appearance="atelier", hud=True, height=1.8), {"radial": 16}, seed=57)`
- Windows Agent fixed operations `stage_production → build_production → export_gltf`, run by
  **Blender 5.0.1 as the PyPI `bpy` module** through a CLI shim (no Blender binary was
  downloadable in the cloud environment)
- FORM's own `inspect_production_export` readback: verified, 106 meshes, 1 skin, 4 animations,
  SHA-256 `3b09c515cc053c1404f0b2986a3a14a99c74273b211f3795b8e8cc5edbc7df0b`

Not included: FORM's numeric candidate search, renders and the production job record (the
stages that need a GPU/display were skipped). FORM's own validation used Blender 5.2 on
Windows; regenerate there to compare. This is a synthetic procedural character, not a
professional asset, and says nothing about artistic quality.
