"""
api/routes.py
FastAPI endpoints for DYNAFIT pipeline orchestration.
- POST /runs (Upload BRD, trigger pipeline)
- GET /runs/{id} (Check status)
- GET /runs/{id}/review (Get required human reviews)
- PATCH /runs/{id}/review (Submit consultant overrides)
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import structlog
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from pydantic import BaseModel
from typing import List

from api.dependencies import verify_api_key
from core.config.settings import settings
from core.schemas.enums import RunStatus
from core.state.graph import build_graph
from core.state.requirement_state import make_initial_state
from infrastructure.storage.postgres_client import postgres_client

# We'll use the memory saver for development; production would use PostgresSaver
from langgraph.checkpoint.memory import MemorySaver

log = structlog.get_logger()
router = APIRouter()

# Global checkpointer for the API lifecycle (MemorySaver for prototype)
checkpointer = MemorySaver()
graph = build_graph(checkpointer=checkpointer)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


class RunResponse(BaseModel):
    run_id: str
    status: str
    message: str


class ReviewItem(BaseModel):
    atom_id: str
    text: str
    original_verdict: str
    rationale: str
    matched_capability: str | None
    gap_description: str | None


class ReviewListResponse(BaseModel):
    run_id: str
    status: str
    needs_review_count: int
    items: List[ReviewItem]


class ConsultantDecisionInput(BaseModel):
    atom_id: str
    verdict: str
    reason: str
    reviewed_by: str


class ReviewSubmitRequest(BaseModel):
    decisions: List[ConsultantDecisionInput]


@router.post("/runs", response_model=RunResponse, dependencies=[Depends(verify_api_key)])
async def create_run(files: List[UploadFile] = File(...)):
    """
    Ingest files and start the pipeline up to the validation interrupt.
    """
    run_id = str(uuid4())
    saved_paths = []

    for f in files:
        safe_name = f"{run_id}_{f.filename}"
        path = Path(settings.UPLOAD_DIR) / safe_name
        
        content = await f.read()
        with open(path, "wb") as out_f:
            out_f.write(content)
        saved_paths.append(str(path))

    await postgres_client.create_run(run_id=run_id, source_files=saved_paths)
    await postgres_client.update_run_status(run_id, RunStatus.RUNNING)

    # Initial state
    state = make_initial_state(run_id=run_id, source_files=saved_paths)
    config = {"configurable": {"thread_id": run_id}}

    try:
        # Run graph in background (or await it depending on architecture).
        # We await it here. The graph pauses before `validation`.
        final_state = await graph.ainvoke(state, config=config)

        # Update run status
        human_review = final_state.get("human_review_required", [])
        if human_review:
            await postgres_client.update_run_status(run_id, RunStatus.AWAITING_REVIEW)
            msg = f"Pipeline paused. {len(human_review)} items require consultant review."
            status = RunStatus.AWAITING_REVIEW.value
        else:
            await postgres_client.update_run_status(run_id, RunStatus.COMPLETED)
            msg = "Pipeline completed successfully without Human-in-the-Loop interrupt."
            status = RunStatus.COMPLETED.value
            
        return RunResponse(run_id=run_id, status=status, message=msg)

    except Exception as e:
        log.error("run_failed", run_id=run_id, error=str(e), exc_info=True)
        await postgres_client.update_run_status(run_id, RunStatus.FAILED)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}/review", response_model=ReviewListResponse, dependencies=[Depends(verify_api_key)])
async def get_review_items(run_id: str):
    """
    Get items flagged for human review. 
    """
    config = {"configurable": {"thread_id": run_id}}
    state_tuple = await graph.aget_state(config)
    
    if not state_tuple or not hasattr(state_tuple, "values"):
        raise HTTPException(status_code=404, detail="Run state not found.")
        
    state = state_tuple.values
    review_ids = state.get("human_review_required", [])
    if not review_ids:
        return ReviewListResponse(
            run_id=run_id,
            status="No review required",
            needs_review_count=0,
            items=[]
        )

    # Reconstruct ReviewItem list
    atoms = {str(a.id): a for a in state.get("atoms", [])}
    results = {str(r.atom_id): r for r in state.get("classification_results", [])}

    items = []
    for aid in review_ids:
        if aid in atoms and aid in results:
            res = results[aid]
            items.append(
                ReviewItem(
                    atom_id=aid,
                    text=atoms[aid].text,
                    original_verdict=res.verdict.value,
                    rationale=res.rationale,
                    matched_capability=res.matched_capability,
                    gap_description=res.gap_description,
                )
            )

    return ReviewListResponse(
        run_id=run_id,
        status=RunStatus.AWAITING_REVIEW.value,
        needs_review_count=len(items),
        items=items
    )


@router.patch("/runs/{run_id}/review", response_model=RunResponse, dependencies=[Depends(verify_api_key)])
async def submit_review(run_id: str, payload: ReviewSubmitRequest):
    """
    Submit human decisions and resume the pipeline (Phase 5 Validation).
    """
    config = {"configurable": {"thread_id": run_id}}
    state_tuple = await graph.aget_state(config)
    
    if not state_tuple or not hasattr(state_tuple, "values"):
        raise HTTPException(status_code=404, detail="Run state not found")

    from core.schemas.classification_result import ConsultantDecision
    from core.schemas.enums import Verdict
    from datetime import datetime

    decisions = []
    # Identify what the actual AI verdict was so we know if it's an override
    results = {str(r.atom_id): r for r in state_tuple.values.get("classification_results", [])}

    for dec in payload.decisions:
        orig = results.get(dec.atom_id)
        if not orig:
            continue
        
        is_override = (orig.verdict.value.upper() != dec.verdict.upper())

        try:
            decisions.append(ConsultantDecision(
                atom_id=dec.atom_id,
                verdict=Verdict(dec.verdict.upper()),
                reason=dec.reason,
                reviewed_by=dec.reviewed_by,
                is_override=is_override,
                reviewed_at=datetime.utcnow()
            ))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid verdict for atom {dec.atom_id}: {dec.verdict}")

    try:
        # Patch local state variable
        # We need to inject consultant_decisions into state, and resume graph
        # Since it was interrupted, passing `None` to ainvoke resumes from the interrupt, 
        # but LangGraph allows state updates to be passed.
        new_state_dict = {"consultant_decisions": decisions}
        await graph.aupdate_state(config, new_state_dict)

        await postgres_client.update_run_status(run_id, RunStatus.RUNNING)
        final_state = await graph.ainvoke(None, config=config)
        
        await postgres_client.update_run_status(run_id, RunStatus.COMPLETED)
        return RunResponse(run_id=run_id, status=RunStatus.COMPLETED.value, message="Pipeline complete. Output generated.")

    except Exception as e:
        log.error("run_resume_failed", run_id=run_id, error=str(e), exc_info=True)
        await postgres_client.update_run_status(run_id, RunStatus.FAILED)
        raise HTTPException(status_code=500, detail=str(e))
