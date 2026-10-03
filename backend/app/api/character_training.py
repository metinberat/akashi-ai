"""Authenticated, explicitly initiated headless expert practice and recipe APIs."""
import asyncio
import json

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.expertise.training.contracts import TrainingRequest
from app.api.expertise import workshop_call
from app.expertise.training.blender import TrainingBlenderAdapter
from app.expertise.schema import Source
from app.expertise.training.datasets import build as build_dataset

router = APIRouter(prefix="/expertise", tags=["character-training"], dependencies=[Depends(require_api_token)])


@router.get("/recipes")
async def recipes(core: AkashiCore = Depends(get_core)):
    return {"recipes": await workshop_call(core.expertise.recipes.list)}


@router.get("/recipes/patterns")
async def patterns(core: AkashiCore = Depends(get_core)):
    return {"patterns": await workshop_call(core.expertise.recipes.compare_patterns)}


@router.get("/recipes/{asset_id}")
async def recipe(asset_id: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.recipes.for_asset, asset_id)


@router.post("/training", status_code=201)
async def create(request: TrainingRequest, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.training.create, request)


@router.get("/training")
async def runs(core: AkashiCore = Depends(get_core)):
    return {"runs": await workshop_call(core.expertise.training.repository.list)}


@router.get("/training/methods")
async def methods(core: AkashiCore = Depends(get_core)):
    return {"best_known_methods": await workshop_call(core.expertise.training.repository.champions),
            "history": await workshop_call(core.expertise.training.repository.history),
            "current_evidence": await workshop_call(core.expertise.training.evidence)}


@router.get("/training/{identifier}")
async def inspect(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.training.repository.get, identifier)


@router.get("/training/method-versions/{identifier}")
async def method_version(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.training.repository.method_version, identifier)


@router.get("/training/{identifier}/exercises")
async def exercises(identifier: str, core: AkashiCore = Depends(get_core)):
    return {"exercises": await workshop_call(core.expertise.training.repository.exercises, identifier)}


@router.get("/training/{identifier}/attempts")
async def attempts(identifier: str, limit: int = Query(100, ge=1, le=1000), core: AkashiCore = Depends(get_core)):
    await workshop_call(core.expertise.training.repository.get, identifier)
    return {"attempts": await workshop_call(core.expertise.training.repository.attempts, identifier, limit)}


@router.post("/training/{identifier}/run")
async def run(identifier: str, exercises: int = Query(1, ge=1, le=32), seconds: int = Query(120, ge=1, le=300), core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.training.run, identifier, exercises, seconds)


@router.post("/training/{identifier}/start", status_code=202)
@router.post("/training/{identifier}/resume", status_code=202)
async def start(identifier: str, core: AkashiCore = Depends(get_core)):
    try:
        return await core.expertise.training_host.start(identifier)
    except KeyError as exc:
        raise HTTPException(404, "Training run was not found.") from exc
    except ValueError as exc:
        raise HTTPException(409, "Training worker is already active.") from exc


@router.post("/training/{identifier}/pause")
async def pause(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.training.repository.request, identifier, "pause")


@router.post("/training/{identifier}/cancel")
async def cancel(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.training.repository.request, identifier, "cancel")


@router.get("/training/{identifier}/dataset")
async def dataset(identifier: str, include_synthetic: bool = False, limit: int = Query(100, ge=1, le=2048),
                  view: str = Query("workflow", pattern="^(workflow|weights|joint_placement|preferences)$"), core: AkashiCore = Depends(get_core)):
    if include_synthetic and view != "workflow":
        return await workshop_call(build_dataset, core.expertise.training, identifier, view)
    return await workshop_call(core.expertise.training.dataset, identifier, include_synthetic, limit)


@router.get("/training/{identifier}/dataset.jsonl")
async def dataset_file(identifier: str, include_synthetic: bool = False, view: str = Query("workflow", pattern="^(workflow|weights|joint_placement|preferences)$"), core: AkashiCore = Depends(get_core)):
    value = await workshop_call(build_dataset, core.expertise.training, identifier, view) if include_synthetic and view != "workflow" else await workshop_call(core.expertise.training.dataset, identifier, include_synthetic, 2048)
    return Response("\n".join(json.dumps(r, allow_nan=False, ensure_ascii=False) for r in value["records"]), media_type="application/x-ndjson",
                    headers={"Content-Disposition": 'attachment; filename="character-practice.jsonl"'})


@router.get("/training/{identifier}/artifacts/{exercise_id}")
async def artifact(identifier: str, exercise_id: str, version: str = Query("best", pattern="^(best|input|reference)$"), core: AkashiCore = Depends(get_core)):
    exercise = await workshop_call(core.expertise.training.repository.exercise, exercise_id)
    if exercise["run_id"] != identifier:
        raise HTTPException(404, "Exercise does not belong to this run.")
    return await workshop_call(core.expertise.training.repository.document, exercise[version+"_digest"])


class ApplyLearnedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=128)
    method_version: str = Field(min_length=1, max_length=128)


class BlenderTrainingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exercise_id: str = Field(min_length=1, max_length=128)
    output_directory: str = Field(min_length=1, max_length=2000)


class BlenderIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=2000)
    output_directory: str = Field(min_length=1, max_length=2000)
    source: Source


@router.post("/characters/ingest-blender", status_code=201)
async def ingest_blender(request: BlenderIngestRequest, core: AkashiCore = Depends(get_core)):
    try:
        return await TrainingBlenderAdapter(core.desktop, core.expertise).ingest_blender(request.project, request.output_directory, request.source)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, "Blender inspection/transport failed; check approved roots and desktop availability.") from exc


@router.post("/training/{identifier}/export-blender")
async def export_blender(identifier: str, request: BlenderTrainingRequest, core: AkashiCore = Depends(get_core)):
    try:
        return await TrainingBlenderAdapter(core.desktop, core.expertise).materialize(identifier, request.exercise_id, request.output_directory)
    except KeyError as exc:
        raise HTTPException(404, "Training exercise was not found.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, "Application verification failed; numeric best checkpoint retained. Inspect application evidence.") from exc


@router.get("/training/{identifier}/application-evidence")
async def application_evidence(identifier: str, core: AkashiCore = Depends(get_core)):
    return {"evidence": await workshop_call(TrainingBlenderAdapter(core.desktop, core.expertise).evidence, identifier)}


@router.post("/training/apply-method", status_code=201)
async def apply_method(request: ApplyLearnedRequest, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.propose_learned_method, request.asset_id, request.method_version)
