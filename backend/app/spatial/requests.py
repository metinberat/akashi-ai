"""Public Spatial Lab request commands: the single input contract.

Every input method — hand gestures, natural language, UI controls, AKASHI
tools, replay — submits these requests. ``compiler.py`` resolves references
and relative operations into concrete scene commands for the pure reducer.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

RefKind = Literal[
    "selected", "deictic", "only", "last_touched", "last_moved", "leftmost", "rightmost",
    "largest", "smallest", "form", "latest_version", "nearest_anchor", "label",
]
Anchor = Literal["left_hand", "right_hand"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ObjectRef(Strict):
    """Either a concrete object id or a semantic reference resolved against the scene."""

    id: Optional[str] = Field(default=None, max_length=32)
    ref: Optional[RefKind] = None
    label: Optional[str] = Field(default=None, min_length=1, max_length=80)
    anchor: Optional[Anchor] = None

    @model_validator(mode="after")
    def one_kind(self) -> "ObjectRef":
        if (self.id is None) == (self.ref is None):
            raise ValueError("Reference needs exactly one of id or ref.")
        if self.ref == "label" and not self.label:
            raise ValueError("A label reference needs label text.")
        if self.ref == "nearest_anchor" and not self.anchor:
            raise ValueError("nearest_anchor needs an anchor.")
        return self


def finite_vector(value: Optional[List[float]], size: int) -> Optional[List[float]]:
    if value is not None and (len(value) != size or not all(math.isfinite(v) for v in value)):
        raise ValueError(f"Expected {size} finite numbers.")
    return value


class TransformValue(Strict):
    position: List[float]
    rotation: List[float]
    scale: float

    @field_validator("position")
    @classmethod
    def _position(cls, value):
        return finite_vector(value, 3)

    @field_validator("rotation")
    @classmethod
    def _rotation(cls, value):
        return finite_vector(value, 4)


class FormSelector(Strict):
    project_id: Optional[str] = Field(default=None, max_length=128)
    version: str = Field(default="latest", min_length=1, max_length=128)


class AddAsset(Strict):
    type: Literal["scene.add_asset"]
    asset_id: Optional[str] = Field(default=None, max_length=64)
    form: Optional[FormSelector] = None
    fixture: Optional[Literal["calibration"]] = None
    label: Optional[str] = Field(default=None, min_length=1, max_length=80)
    position: Optional[List[float]] = None

    @model_validator(mode="after")
    def one_source(self) -> "AddAsset":
        if sum(x is not None for x in (self.asset_id, self.form, self.fixture)) != 1:
            raise ValueError("Add exactly one of asset_id, form or fixture.")
        finite_vector(self.position, 3)
        return self


class Remove(Strict):
    type: Literal["scene.remove"]
    target: ObjectRef


class Select(Strict):
    type: Literal["selection.select"]
    target: Optional[ObjectRef] = None


class Inspect(Strict):
    type: Literal["view.inspect"]
    target: Optional[ObjectRef] = None


class Transform(Strict):
    type: Literal["object.transform"]
    target: ObjectRef
    mode: Literal["set", "translate", "rotate", "scale", "reset", "center", "to_anchor"]
    transform: Optional[TransformValue] = None
    delta: Optional[List[float]] = None
    axis: Literal["x", "y", "z"] = "y"
    degrees: Optional[float] = Field(default=None, ge=-3600, le=3600)
    factor: Optional[float] = Field(default=None, gt=0, le=100)
    anchor: Optional[Anchor] = None
    lease_id: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def parameters(self) -> "Transform":
        finite_vector(self.delta, 3)
        required = {"set": self.transform, "translate": self.delta, "rotate": self.degrees,
                    "scale": self.factor, "to_anchor": self.anchor}
        if self.mode in required and required[self.mode] is None:
            raise ValueError(f"Transform mode {self.mode!r} is missing its parameter.")
        if self.lease_id and self.mode != "set":
            raise ValueError("Only absolute gesture commits carry a lease.")
        return self


class Visibility(Strict):
    type: Literal["object.visibility"]
    target: ObjectRef
    visible: bool


class Display(Strict):
    type: Literal["object.display"]
    target: ObjectRef
    skeleton: Optional[bool] = None
    form_hud: Optional[bool] = None
    bounds: Optional[bool] = None

    @model_validator(mode="after")
    def something(self) -> "Display":
        if self.skeleton is None and self.form_hud is None and self.bounds is None:
            raise ValueError("Display needs at least one flag.")
        return self


class AnimationControl(Strict):
    type: Literal["animation.control"]
    target: ObjectRef
    action: Literal["play", "pause", "stop"]
    clip: Optional[str] = Field(default=None, min_length=1, max_length=80)
    speed: Optional[float] = Field(default=None, gt=0, le=10)


class Version(Strict):
    type: Literal["object.version"]
    target: ObjectRef
    version: str = Field(min_length=1, max_length=128)


class Rename(Strict):
    type: Literal["object.rename"]
    target: ObjectRef
    label: str = Field(min_length=1, max_length=80)


class ViewSet(Strict):
    type: Literal["view.set"]
    hud_visible: Optional[bool] = None
    vfx_visible: Optional[bool] = None

    @model_validator(mode="after")
    def something(self) -> "ViewSet":
        if self.hud_visible is None and self.vfx_visible is None:
            raise ValueError("View needs hud_visible or vfx_visible.")
        return self


class Undo(Strict):
    type: Literal["history.undo"]


class Redo(Strict):
    type: Literal["history.redo"]


SpatialRequest = Annotated[
    Union[AddAsset, Remove, Select, Inspect, Transform, Visibility, Display, AnimationControl,
          Version, Rename, ViewSet, Undo, Redo],
    Field(discriminator="type"),
]
REQUEST_ADAPTER: TypeAdapter = TypeAdapter(SpatialRequest)
REQUEST_LIST_ADAPTER: TypeAdapter = TypeAdapter(List[SpatialRequest])
REQUEST_TYPES = sorted(model.model_fields["type"].annotation.__args__[0] for model in (
    AddAsset, Remove, Select, Inspect, Transform, Visibility, Display, AnimationControl,
    Version, Rename, ViewSet, Undo, Redo))

# Requests that remove user-visible state need explicit confirmation from any origin.
CONFIRM_REQUESTS = {"scene.remove"}


Modality = Literal["gesture", "touch", "pointer", "language", "voice", "ui"]


class RemoteProvenance(Strict):
    """Which device, session and message produced a remote change (set by Core, never by the client)."""

    device_id: str = Field(min_length=1, max_length=64)
    device_name: str = Field(min_length=1, max_length=100)
    device_type: str = Field(min_length=1, max_length=40)
    session: str = Field(pattern=r"^rs-[0-9a-f]{16}$")
    session_kind: Literal["device", "owner"]
    modality: Modality
    message_id: str = Field(min_length=8, max_length=64)
    seq: int = Field(ge=1)
    sent_at_ms: float = Field(ge=0)
    received_at: str = Field(min_length=1, max_length=40)
    transport: str = Field(min_length=1, max_length=20)


class ApprovalProvenance(Strict):
    """Who confirmed a change that required confirmation."""

    decision: Literal["approved"]
    by: Literal["owner", "device", "requester"]
    device_id: Optional[str] = Field(default=None, max_length=64)
    device_name: Optional[str] = Field(default=None, max_length=100)
    session: Optional[str] = Field(default=None, max_length=32)
    at: str = Field(min_length=1, max_length=40)


class Origin(Strict):
    kind: Literal["gesture", "language", "ui", "tool", "replay", "system", "remote"]
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:/+\- ]+$")
    interaction_id: Optional[str] = Field(default=None, max_length=128)
    input: Optional[Dict[str, Any]] = None
    remote: Optional[RemoteProvenance] = None
    approval: Optional[ApprovalProvenance] = None

    @model_validator(mode="after")
    def remote_matches_kind(self) -> "Origin":
        if (self.kind == "remote") != (self.remote is not None):
            raise ValueError("A remote origin carries remote provenance, and only a remote origin does.")
        return self


def parse_request(value: Any):
    return REQUEST_ADAPTER.validate_python(value)
