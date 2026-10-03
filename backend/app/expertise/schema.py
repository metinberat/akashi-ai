from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=2000)
    category: Literal["asset_observation", "synthetic_fixture"]
    synthetic: bool
    version: Optional[str] = Field(default=None, max_length=200)
    license: Optional[str] = Field(default=None, max_length=300)
    related_task_id: Optional[str] = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def consistent(self) -> "Source":
        if self.synthetic != (self.category == "synthetic_fixture"):
            raise ValueError("Synthetic provenance and source category must agree.")
        return self


class Joint(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    parent: Optional[str] = Field(default=None, max_length=200)
    translation: Optional[List[float]] = Field(default=None, min_length=3, max_length=3)
    rotation: Optional[List[float]] = Field(default=None, min_length=4, max_length=4)
    scale: Optional[List[float]] = Field(default=None, min_length=3, max_length=3)
    matrix: Optional[List[float]] = Field(default=None, min_length=16, max_length=16)
    inverse_bind_matrix: Optional[List[float]] = Field(default=None, min_length=16, max_length=16)
    constraints: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Mesh(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(max_length=300)
    vertex_count: int = Field(ge=0, le=50_000_000)
    edge_count: Optional[int] = Field(default=None, ge=0)
    face_count: Optional[int] = Field(default=None, ge=0)
    positions: Optional[List[List[float]]] = Field(default=None, max_length=200000)
    faces: Optional[List[List[int]]] = Field(default=None, max_length=200000)
    uv_maps: List[str] = Field(default_factory=list, max_length=100)
    materials: List[str] = Field(default_factory=list, max_length=1000)
    skin_id: Optional[str] = None
    normals: bool = False
    tangents: bool = False
    morph_targets: List[str] = Field(default_factory=list, max_length=1000)
    modifiers: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Skin(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    mesh_id: str = Field(min_length=1, max_length=200)
    joints: List[str] = Field(max_length=10000)
    weights: Optional[List[Dict[str, float]]] = Field(default=None, max_length=200000)


class Animation(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(max_length=300)
    duration: Optional[float] = Field(default=None, ge=0)
    frame_rate: Optional[float] = Field(default=None, gt=0)
    channels: List[Dict[str, Any]] = Field(default_factory=list, max_length=10000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CharacterDocument(BaseModel):
    """Observed interchange data. Unknown/missing values remain absent, not invented."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=300)
    coordinate_system: Dict[str, Any] = Field(default_factory=dict)
    joints: List[Joint] = Field(default_factory=list, max_length=10000)
    meshes: List[Mesh] = Field(default_factory=list, max_length=10000)
    skins: List[Skin] = Field(default_factory=list, max_length=10000)
    materials: List[Dict[str, Any]] = Field(default_factory=list, max_length=10000)
    animations: List[Animation] = Field(default_factory=list, max_length=1000)
    objects: List[Dict[str, Any]] = Field(default_factory=list, max_length=10000)
    unavailable: List[str] = Field(default_factory=list, max_length=100)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "CharacterDocument":
        import math
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Character data cannot contain NaN or infinite numeric values.")
            if isinstance(value, dict):
                for item in value.values(): finite(item)
            elif isinstance(value, list):
                for item in value: finite(item)
        finite(self.model_dump())
        ids = {joint.id for joint in self.joints}
        if len(ids) != len(self.joints):
            raise ValueError("Duplicate joint identifiers.")
        parents = {joint.id: joint.parent for joint in self.joints}
        for joint in self.joints:
            if joint.parent is not None and joint.parent not in ids:
                raise ValueError("Joint parent does not exist.")
        done = set()
        for joint in self.joints:
            chain = set()
            cursor: Optional[str] = joint.id
            while cursor is not None and cursor not in done:
                if cursor in chain:
                    raise ValueError("Skeleton hierarchy contains a cycle.")
                chain.add(cursor)
                cursor = parents[cursor]
            done.update(chain)
        mesh_ids = {mesh.id for mesh in self.meshes}
        if sum(mesh.vertex_count for mesh in self.meshes if mesh.positions is not None or mesh.faces is not None) > 200000:
            raise ValueError("Detailed geometry exceeds the analysis sample budget; use metadata-only meshes.")
        if len(mesh_ids) != len(self.meshes) or len({skin.id for skin in self.skins}) != len(self.skins):
            raise ValueError("Duplicate mesh/skin identifiers.")
        for mesh in self.meshes:
            if mesh.positions is not None and len(mesh.positions) != mesh.vertex_count:
                raise ValueError("Position count does not match mesh vertices.")
            if mesh.faces is not None and any(len(face) < 3 or any(index < 0 or index >= mesh.vertex_count for index in face) for face in mesh.faces):
                raise ValueError("Invalid mesh face indices.")
            if mesh.positions is not None and any(len(position) != 3 for position in mesh.positions):
                raise ValueError("Mesh positions must have three components.")
            if mesh.skin_id and mesh.skin_id not in {skin.id for skin in self.skins}:
                raise ValueError("Mesh references an unknown skin.")
        for skin in self.skins:
            if len(set(skin.joints)) != len(skin.joints):
                raise ValueError("Skin palette contains duplicate joints.")
            if skin.mesh_id not in mesh_ids or not set(skin.joints).issubset(ids):
                raise ValueError("Skin references an unknown mesh or joint.")
            mesh = next(mesh for mesh in self.meshes if mesh.id == skin.mesh_id)
            if skin.weights is not None:
                if len(skin.weights) != mesh.vertex_count:
                    raise ValueError("Skin weights must match mesh vertex count.")
                for weights in skin.weights:
                    if not set(weights).issubset(set(skin.joints)) or any(weight < 0 or weight > 1 for weight in weights.values()):
                        raise ValueError("Invalid joint influence or weight.")
        for clip in self.animations:
            for channel in clip.channels:
                times = channel.get("times", [])
                if not isinstance(times, list) or any(not isinstance(value, (int, float)) for value in times):
                    raise ValueError("Animation times must be numeric samples.")
                if any(right < left for left, right in zip(times, times[1:])):
                    raise ValueError("Animation sample times must be ordered.")
                count = channel.get("keyframe_count", len(times))
                if not isinstance(count, int) or count < 0 or count > 200000:
                    raise ValueError("Invalid animation keyframe count.")
                if times and count != len(times):
                    raise ValueError("Animation keyframe count mismatch.")
        if sum(len(channel.get("times", [])) for clip in self.animations for channel in clip.channels) > 200000:
            raise ValueError("Animation exceeds the keyframe sample budget.")
        return self
