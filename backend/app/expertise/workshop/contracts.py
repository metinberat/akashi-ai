from __future__ import annotations

import math
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Landmark(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    parent: Optional[str] = Field(default=None, max_length=200)
    head: List[float] = Field(min_length=3, max_length=3)
    tail: List[float] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def segment(self):
        if math.dist(self.head, self.tail) < 1e-8:
            raise ValueError("A joint landmark needs a nonzero bone segment.")
        return self


class Recipe(BaseModel):
    """Only these numeric operations can run. Retrieved prose is never executable."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    operation: Literal["normalize_weights", "prune_influences", "smooth_weights", "spatial_bind", "align_landmarks", "construct_rig"]
    skin_id: Optional[str] = Field(default=None, max_length=200)
    mesh_id: Optional[str] = Field(default=None, max_length=200)
    max_influences: int = Field(default=4, ge=1, le=8)
    strength: float = Field(default=0.2, ge=0.01, le=0.8)
    iterations: int = Field(default=1, ge=1, le=8)
    distance_power: float = Field(default=4, ge=1, le=8)
    landmarks: List[Landmark] = Field(default_factory=list, max_length=128)


class WorkshopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(default="Improve skinning integrity and tested deformation without regressions.", min_length=1, max_length=1000)
    max_attempts: int = Field(default=8, ge=1, le=16)
    # Optional explicit construction/landmark proposal. Every proposal must pass the same quality gate.
    proposals: List[Recipe] = Field(default_factory=list, max_length=16)


EVALUATOR_VERSION = "pose-quality-1.1"
POLICY_VERSION = "conservative-improvement-1.0"
