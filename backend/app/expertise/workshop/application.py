from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


class PoseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    joint: str = Field(min_length=1, max_length=200)
    mesh: str = Field(min_length=1, max_length=200)
    degrees: float = Field(ge=-180, le=180)
    axis: List[float] = Field(min_length=3, max_length=3)
    split: Literal["train", "held_out"]
    mean_log_strain: float = Field(ge=0, le=100)
    collapsed_edges: int = Field(ge=0, le=200000)
    sampled_edges: int = Field(gt=0, le=200000)


class ApplicationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    method: Literal["actual_blender_evaluated_modifier_mesh"]
    application_version: str = Field(min_length=1, max_length=100)
    poses: List[PoseEvidence] = Field(min_length=1, max_length=1000)
    scope: Literal["numeric_stress_tests_not_artistic_certification"]
    verified: bool


def compare_application(before: ApplicationEvidence, after: ApplicationEvidence):
    def key(p): return (p.joint, p.mesh, p.degrees, tuple(p.axis), p.split)
    old, new = {key(p): p for p in before.poses}, {key(p): p for p in after.poses}
    reasons = []
    if not before.verified or not after.verified:
        reasons.append("Application reported missing pose evidence.")
    if len(old) != len(before.poses) or len(new) != len(after.poses) or set(old) != set(new):
        reasons.append("Application probe identities are missing/duplicated or changed.")
    if before.application_version != after.application_version:
        reasons.append("Application version changed between evidence runs.")
    if not any(p.split == "held_out" for p in after.poses):
        reasons.append("Held-out application poses were not tested.")
    for identifier in set(old) & set(new):
        a, b = old[identifier], new[identifier]
        if b.sampled_edges != a.sampled_edges or b.collapsed_edges > a.collapsed_edges or b.mean_log_strain > max(a.mean_log_strain*1.12, a.mean_log_strain+.015):
            reasons.append("Application deformation regressed: " + a.joint)
    return {"accepted": not reasons, "reasons": reasons, "before": before.model_dump(), "after": after.model_dump(),
            "scope": "actual_application_numeric_pose_comparison", "professional_quality_certified": False}
