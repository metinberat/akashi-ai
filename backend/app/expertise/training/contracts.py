from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GENERATOR_VERSION = "procedural-character-1.0"
TRAINER_VERSION = "paired-expert-practice-1.0"
RECIPE_VERSION = "production-relations-1.0"


class TrainingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_asset_ids: List[str] = Field(default_factory=list, max_length=20)
    seed: int = Field(default=57, ge=0, le=2**31-1, strict=True)
    max_exercises: int = Field(default=16, ge=1, le=128, strict=True)
    candidates_per_exercise: int = Field(default=4, ge=2, le=8, strict=True)
    start_level: int = Field(default=0, ge=0, le=5, strict=True)
    max_level: int = Field(default=5, ge=0, le=5, strict=True)
    adaptive_start: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def limits(self):
        if self.max_level < self.start_level or any(not s or len(s) > 128 for s in self.source_asset_ids):
            raise ValueError("Invalid curriculum or source identifiers.")
        return self


class MethodSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: Literal[1] = 1
    binding: Literal["preserve", "spatial", "segmented"] = "spatial"
    reconstruct: bool = False
    distance_power: float = Field(default=2, ge=1, le=8)
    max_influences: int = Field(default=2, ge=1, le=8, strict=True)
    smoothing: float = Field(default=0, ge=0, le=.8)
    smoothing_iterations: int = Field(default=1, ge=1, le=8, strict=True)
