from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "character-production-1.0"
Channel = Annotated[float, Field(ge=0, le=1)]


class Design(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    height: float = Field(default=1.8, ge=0.6, le=3)
    head_ratio: float = Field(default=0.14, ge=0.10, le=0.22)
    shoulder_ratio: float = Field(default=0.26, ge=0.18, le=0.38)
    build: Literal["slender", "balanced", "strong"] = "balanced"
    clothing: Literal["bodysuit", "coat", "armor"] = "coat"
    hair: Literal["none", "short", "long"] = "short"
    skin_color: list[Channel] = Field(
        default_factory=lambda: [0.62, 0.38, 0.27], min_length=3, max_length=3
    )
    cloth_color: list[Channel] = Field(
        default_factory=lambda: [0.022, 0.027, 0.035], min_length=3, max_length=3
    )
    accent_color: list[Channel] = Field(
        default_factory=lambda: [0.65, 0.015, 0.025], min_length=3, max_length=3
    )
    hud: bool = Field(default=False, strict=True)
    facial: bool = Field(default=True, strict=True)
    appearance: Literal["classic", "atelier"] = "classic"


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(
        default="Build a stylized humanoid character", min_length=1, max_length=4000
    )
    design: Design | None = None
    source_asset_id: str | None = Field(default=None, max_length=128)
    source_project: str | None = Field(default=None, max_length=2000)
    output_directory: str | None = Field(default=None, max_length=2000)
    max_candidates: int = Field(default=3, ge=1, le=6, strict=True)
    seed: int = Field(default=57, ge=0, le=2**31 - 1, strict=True)
    reference_image: str | None = Field(default=None, max_length=2000000, exclude=True)
    use_models: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def source_identity(self):
        if self.source_project and not self.source_asset_id:
            raise ValueError(
                "A supplied Blender project must have ingested source provenance."
            )
        return self


class CandidateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    radial: int = Field(default=12, ge=8, le=32, strict=True)
    clearance: float = Field(default=0.012, ge=0.003, le=0.05)
    distance_power: float = Field(default=2, ge=1, le=4)


def validate_colors(design):
    for field in ("skin_color", "cloth_color", "accent_color"):
        if any(not 0 <= v <= 1 for v in getattr(design, field)):
            raise ValueError("Design colors must be finite normalized channels.")
    return design
