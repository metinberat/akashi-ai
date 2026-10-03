import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from pydantic import ConfigDict
from app.expertise.workshop.contracts import WorkshopRequest
from app.expertise.blender_workflow import BlenderWorkshopWorkflow

from app.core.absolute import AkashiCore, get_core
from app.core.auth import require_api_token
from app.expertise.schema import CharacterDocument, Source
from app.expertise.parsers import MAX_BYTES

router = APIRouter(prefix="/expertise", tags=["expertise"], dependencies=[Depends(require_api_token)])


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str = Field(min_length=1, max_length=128)


class MaterializeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=2000)
    output_directory: str = Field(min_length=1, max_length=2000)


class RefineRequest(MaterializeRequest):
    max_cycles: int = Field(default=3, ge=1, le=3, strict=True)


@router.post("/workshops/{identifier}/refine-blender")
async def refine_workshop(identifier: str, request: RefineRequest, core: AkashiCore = Depends(get_core)):
    try:
        return await BlenderWorkshopWorkflow(core.desktop, core.expertise.workshop).refine(identifier, request.project, request.output_directory, request.max_cycles)
    except KeyError as exc:
        raise HTTPException(404, "Character workshop record was not found.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, "Refinement paused or failed. Best checkpoint/source retained; inspect application evidence.") from exc


@router.post("/workshops/{identifier}/materialize-blender")
async def materialize_workshop(identifier: str, request: MaterializeRequest, core: AkashiCore = Depends(get_core)):
    try:
        return await BlenderWorkshopWorkflow(core.desktop, core.expertise.workshop).materialize(identifier, request.project, request.output_directory)
    except KeyError as exc:
        raise HTTPException(404, "Character workshop record was not found.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, "Application verification failed; source/baseline retained. Inspect workshop state.") from exc


async def workshop_call(function, *args):
    try:
        return await asyncio.to_thread(function, *args)
    except KeyError as exc:
        raise HTTPException(404, "Character workshop record was not found.") from exc
    except ValueError as exc:
        raise HTTPException(409, "Workshop precondition failed; inspect state, ownership and evidence.") from exc


@router.post("/workshops", status_code=201)
async def create_workshop(request: WorkshopRequest, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.create, request)


@router.get("/workshops")
async def workshops(core: AkashiCore = Depends(get_core)):
    return {"workshops": await workshop_call(core.expertise.workshop.repository.list)}


@router.get("/workshops/evidence")
async def workshop_evidence(include_synthetic: bool = False, core: AkashiCore = Depends(get_core)):
    return {"evidence": await workshop_call(core.expertise.workshop.repository.evidence, include_synthetic)}


@router.get("/workshops/dataset")
async def workshop_dataset(include_synthetic: bool = False, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.dataset, include_synthetic)


@router.get("/workshops/{identifier}")
async def workshop(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.repository.get, identifier)


@router.post("/workshops/{identifier}/run")
async def run_workshop(identifier: str, steps: int = Query(default=16, ge=1, le=16), core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.run, identifier, steps)


@router.post("/workshops/{identifier}/cancel")
async def cancel_workshop(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.repository.cancel, identifier)


@router.post("/workshops/{identifier}/rollback")
async def rollback_workshop(identifier: str, request: RollbackRequest, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.repository.rollback, identifier, request.version_id)


@router.get("/workshops/{identifier}/versions")
async def workshop_versions(identifier: str, core: AkashiCore = Depends(get_core)):
    return {"versions": await workshop_call(core.expertise.workshop.repository.versions, identifier)}


@router.get("/versions/{identifier}")
async def character_version(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.repository.version, identifier)


@router.get("/workshops/{identifier}/weight-patch")
async def workshop_patch(identifier: str, core: AkashiCore = Depends(get_core)):
    return await workshop_call(core.expertise.workshop.weight_patch, identifier)


class IngestRequest(BaseModel):
    character: CharacterDocument
    source: Source


class CompareRequest(BaseModel):
    left: str = Field(max_length=128)
    right: str = Field(max_length=128)


class ValidateRequest(BaseModel):
    evidence_reference: str = Field(min_length=1, max_length=2000)
    method: str = Field(min_length=1, max_length=300)
    task_id: Optional[str] = Field(default=None, max_length=128)


@router.post("/characters", status_code=201)
async def ingest(request: IngestRequest, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    content = request.character.model_dump_json().encode()
    try:
        return await asyncio.to_thread(core.expertise.ingest, "character.json", content, request.source)
    except ValueError as exc:
        raise HTTPException(422, "Invalid character source or analysis budget exceeded.") from exc


@router.post("/characters/upload", status_code=201)
async def upload(file: UploadFile = File(...), provenance: str = Form(..., max_length=5000), core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        source = Source.model_validate_json(provenance)
        content = await file.read(MAX_BYTES + 1)
        return await asyncio.to_thread(core.expertise.ingest, file.filename or "", content, source)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(422, "Invalid or unsupported character source; inspect format and references.") from exc
    finally:
        await file.close()


@router.get("/characters")
async def characters(limit: int = Query(default=100, ge=1, le=500), core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {"characters": await asyncio.to_thread(core.expertise.store.list_assets, limit)}


@router.get("/characters/{identifier}")
async def character(identifier: str, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(core.expertise.store.asset, identifier)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/compare")
async def compare(request: CompareRequest, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(core.expertise.compare, request.left, request.right)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/knowledge")
async def knowledge(query: str = Query(default="", max_length=500), asset_id: Optional[str] = None,
                    validated_only: bool = False, limit: int = Query(default=20, ge=1, le=200), core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {"knowledge": await asyncio.to_thread(core.expertise.store.knowledge, query, limit, asset_id, validated_only)}


@router.post("/knowledge/{identifier}/validate")
async def validate(identifier: str, request: ValidateRequest, core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    try:
        if request.task_id:
            task = core.autonomy.store.get(request.task_id)
            if not task or task["status"] != "completed":
                raise HTTPException(409, "Validation task must be a completed task.")
        return await asyncio.to_thread(core.expertise.validate, identifier, request.evidence_reference, request.method, request.task_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/experiences")
async def experiences(core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return {"experiences": await asyncio.to_thread(core.expertise.store.experiences)}


@router.get("/dataset")
async def dataset(include_synthetic: bool = False, validated_only: bool = True,
                  limit: int = Query(default=100, ge=1, le=200), core: AkashiCore = Depends(get_core)) -> Dict[str, Any]:
    return await asyncio.to_thread(core.expertise.dataset, include_synthetic, validated_only, limit)
