from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.auth import require_api_token
from app.core.absolute import get_core
from app.api.expertise import workshop_call
from app.expertise.production.contracts import BuildRequest
from app.expertise.production.reference import ReferenceIntelligence

router = APIRouter(
    prefix="/expertise/production",
    tags=["character-production"],
    dependencies=[Depends(require_api_token)],
)


@router.post("", status_code=201)
async def create(request: BuildRequest, core=Depends(get_core)):
    request, evidence = await ReferenceIntelligence(
        getattr(core, "model_router", None)
    ).resolve(request)
    return await workshop_call(core.expertise.production.create, request, evidence)


@router.get("")
async def jobs(core=Depends(get_core)):
    return {"jobs": await workshop_call(core.expertise.production.repository.list)}


@router.get("/lessons")
async def lessons(core=Depends(get_core)):
    return {
        "lessons": await workshop_call(core.expertise.production.repository.lessons)
    }


@router.post("/practice")
async def practice(
    count: int = Query(3, ge=1, le=12),
    seed: int = Query(57, ge=0, le=2147483647),
    core=Depends(get_core),
):
    return await workshop_call(core.expertise.production.practice, count, seed)


@router.get("/{key}")
async def inspect(key: str, core=Depends(get_core)):
    return {
        "job": await workshop_call(core.expertise.production.repository.get, key),
        "trials": await workshop_call(core.expertise.production.repository.trials, key),
    }


@router.post("/{key}/numeric")
async def numeric(key: str, steps: int = Query(6, ge=1, le=6), core=Depends(get_core)):
    return await workshop_call(core.expertise.production.numeric, key, steps)


@router.post("/{key}/start", status_code=202)
@router.post("/{key}/resume", status_code=202)
async def start(key: str, core=Depends(get_core)):
    try:
        return await core.production_host.start(key)
    except KeyError as exc:
        raise HTTPException(404, "Production job missing.") from exc
    except ValueError as exc:
        raise HTTPException(
            409, "Production is busy or requires application reconciliation."
        ) from exc


@router.post("/{key}/pause")
async def pause(key: str, core=Depends(get_core)):
    return await workshop_call(
        core.expertise.production.repository.request, key, "pause"
    )


@router.post("/{key}/cancel")
async def cancel(key: str, core=Depends(get_core)):
    return await workshop_call(
        core.expertise.production.repository.request, key, "cancel"
    )


@router.post("/{key}/reconcile")
async def reconcile(key: str, core=Depends(get_core)):
    try:
        return await core.production_host.reconcile(key)
    except KeyError as exc:
        raise HTTPException(404, "Production job missing.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            409, "Saved effect could not be reconciled; no replay performed."
        ) from exc


@router.get("/{key}/best")
async def best(key: str, core=Depends(get_core)):
    job = await workshop_call(core.expertise.production.repository.get, key)
    if not job["best"]:
        raise HTTPException(409, "No accepted numeric character yet.")
    return await workshop_call(
        core.expertise.production.repository.document, job["best"]["document_digest"]
    )


@router.get("/{key}/dataset")
async def dataset(key: str, include_synthetic: bool = False, core=Depends(get_core)):
    if not include_synthetic:
        await workshop_call(core.expertise.production.repository.get, key)
        return {"records": [], "synthetic_excluded": True}
    return await workshop_call(core.expertise.production.dataset, key)
