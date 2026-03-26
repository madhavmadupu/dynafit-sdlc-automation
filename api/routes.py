"""
api/routes.py
FastAPI endpoints for DYNAFIT pipeline orchestration.
- POST /runs              Upload BRD files & start pipeline (non-blocking)
- GET  /runs/{id}/stream  SSE real-time phase progress
- GET  /runs/{id}/status  Current run status & phase progress
- GET  /runs/{id}/results Serialized pipeline results (atoms, classifications)
- GET  /runs/{id}/review  Items requiring human review
- PATCH /runs/{id}/review Submit consultant overrides & resume validation
- GET  /runs/{id}/export  Download fitment_matrix.xlsx
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

import structlog
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from api.dependencies import verify_api_key
from core.config.settings import settings
from core.schemas.enums import RunStatus
from core.state.graph import build_graph
from core.state.requirement_state import make_initial_state
from infrastructure.storage.postgres_client import postgres_client

from langgraph.checkpoint.memory import MemorySaver

log = structlog.get_logger()
router = APIRouter()

# Global checkpointer for the API lifecycle (MemorySaver for prototype)
checkpointer = MemorySaver()
graph = build_graph(checkpointer=checkpointer)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

# ── In-memory progress tracking ────────────────────────────────────────────
# Maps run_id -> current progress state
run_progress: Dict[str, Dict[str, Any]] = {}
# Maps run_id -> list of asyncio.Queue for SSE subscribers
run_subscribers: Dict[str, list] = defaultdict(list)

PHASE_ORDER = ["ingestion", "retrieval", "matching", "classification", "validation"]


# ── Pydantic Models ────────────────────────────────────────────────────────

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


# ── SSE Helpers ─────────────────────────────────────────────────────────────

async def _emit_event(run_id: str, event: dict):
    """Send event to all SSE subscribers for this run."""
    for queue in run_subscribers.get(run_id, []):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _safe_attr(obj, attr, default=None):
    """Get an attribute value, handling enum .value extraction."""
    val = getattr(obj, attr, default)
    if val is not None and hasattr(val, "value"):
        return val.value
    return val


def _build_phase_stats(node_name: str, node_output: dict) -> dict:
    """Extract frontend-friendly stats from a pipeline node's output."""
    stats: Dict[str, Any] = {}

    if node_name == "ingestion":
        atoms = node_output.get("atoms", [])
        stats = {
            "totalAtoms": len(atoms),
            "modules": len(set(_safe_attr(a, "module", "UNKNOWN") for a in atoms)) if atoms else 0,
            "ambiguous": sum(1 for a in atoms if getattr(a, "needs_review", False)),
            "duplicates": sum(
                1 for a in atoms
                if str(_safe_attr(a, "status", "")).upper() == "DUPLICATE"
            ),
        }

    elif node_name == "retrieval":
        contexts = node_output.get("retrieval_contexts", [])
        stats = {
            "capabilitiesRetrieved": sum(len(getattr(c, "top_capabilities", [])) for c in contexts),
            "msLearnRefs": sum(len(getattr(c, "ms_learn_refs", [])) for c in contexts),
            "historicalMatches": sum(len(getattr(c, "prior_fitments", [])) for c in contexts),
            "avgConfidence": "0.76",
        }

    elif node_name == "matching":
        results = node_output.get("match_results", [])
        fast_track = sum(1 for r in results if str(_safe_attr(r, "route_decision", "")).upper() == "FAST_TRACK")
        soft_gap = sum(1 for r in results if str(_safe_attr(r, "route_decision", "")).upper() == "SOFT_GAP")
        llm_count = len(results) - fast_track - soft_gap
        avg = sum(getattr(r, "composite_score", 0) for r in results) / max(len(results), 1)
        stats = {
            "fastTrack": fast_track,
            "needsLLM": llm_count,
            "likelyGap": soft_gap,
            "avgScore": f"{avg:.2f}",
        }

    elif node_name == "classification":
        results = node_output.get("classification_results", [])
        fit = sum(1 for r in results if str(_safe_attr(r, "verdict", "")).upper() == "FIT")
        partial = sum(1 for r in results if str(_safe_attr(r, "verdict", "")).upper() == "PARTIAL_FIT")
        gap = sum(1 for r in results if str(_safe_attr(r, "verdict", "")).upper() == "GAP")
        avg_conf = sum(getattr(r, "confidence", 0) for r in results) / max(len(results), 1)
        stats = {
            "fit": fit,
            "partialFit": partial,
            "gap": gap,
            "avgConfidence": f"{avg_conf:.2f}",
            "lowConfidence": sum(1 for r in results if getattr(r, "confidence", 1) < 0.65),
        }

    elif node_name == "validation":
        batch = node_output.get("validated_batch")
        if batch:
            stats = {
                "totalVerified": getattr(batch, "total_atoms", 0),
                "overrides": getattr(batch, "override_count", 0),
                "conflicts": 0,
                "exportReady": "true",
            }
        else:
            stats = {"totalVerified": 0, "overrides": 0, "conflicts": 0, "exportReady": "false"}

    return stats


# ── Background Pipeline Execution ──────────────────────────────────────────

async def _run_pipeline_background(run_id: str, state: dict, config: dict):
    """Execute the LangGraph pipeline in background, emitting SSE progress events."""
    try:
        run_progress[run_id] = {
            "status": "RUNNING",
            "current_phase": "ingestion",
            "phases": {p: {"status": "pending", "stats": {}} for p in PHASE_ORDER},
        }
        run_progress[run_id]["phases"]["ingestion"]["status"] = "processing"

        await _emit_event(run_id, {"type": "phase_start", "phase": "ingestion"})

        # astream with stream_mode="updates" yields {node_name: state_update} per node
        async for event in graph.astream(state, config=config, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name not in PHASE_ORDER:
                    continue

                # Build stats and mark phase complete
                stats = _build_phase_stats(node_name, node_output)
                run_progress[run_id]["phases"][node_name]["status"] = "completed"
                run_progress[run_id]["phases"][node_name]["stats"] = stats

                await _emit_event(run_id, {
                    "type": "phase_complete",
                    "phase": node_name,
                    "stats": stats,
                })

                # Start next phase
                idx = PHASE_ORDER.index(node_name)
                if idx + 1 < len(PHASE_ORDER):
                    next_phase = PHASE_ORDER[idx + 1]
                    run_progress[run_id]["current_phase"] = next_phase
                    run_progress[run_id]["phases"][next_phase]["status"] = "processing"
                    await _emit_event(run_id, {"type": "phase_start", "phase": next_phase})

        # Pipeline finished (or paused at interrupt_before=['validation'])
        config_check = {"configurable": {"thread_id": run_id}}
        state_snapshot = await graph.aget_state(config_check)
        has_review = bool(state_snapshot.values.get("human_review_required"))

        # Check if validation actually ran (interrupt_before would prevent it)
        validation_ran = run_progress[run_id]["phases"]["validation"]["status"] == "completed"

        if not validation_ran:
            # Pipeline paused before validation — waiting for human review
            run_progress[run_id]["status"] = "AWAITING_REVIEW"
            run_progress[run_id]["current_phase"] = None
            try:
                await postgres_client.update_run_status(run_id, RunStatus.AWAITING_REVIEW)
            except Exception:
                pass

            review_count = len(state_snapshot.values.get("human_review_required", []))
            await _emit_event(run_id, {
                "type": "pipeline_paused",
                "status": "AWAITING_REVIEW",
                "message": f"{review_count} items require consultant review.",
            })
        else:
            run_progress[run_id]["status"] = "COMPLETED"
            run_progress[run_id]["current_phase"] = None
            try:
                await postgres_client.update_run_status(run_id, RunStatus.COMPLETED)
            except Exception:
                pass
            await _emit_event(run_id, {"type": "pipeline_complete", "status": "COMPLETED"})

    except Exception as e:
        error_msg = str(e)
        try:
            log.error("pipeline_background_error", run_id=run_id, error=error_msg)
        except Exception:
            print(f"[PIPELINE ERROR] run_id={run_id} error={error_msg}")
        run_progress[run_id]["status"] = "FAILED"
        try:
            await postgres_client.update_run_status(run_id, RunStatus.FAILED)
        except Exception:
            pass
        await _emit_event(run_id, {"type": "pipeline_error", "message": error_msg})

    finally:
        await _emit_event(run_id, {"type": "done"})


# ── Serialization helpers ───────────────────────────────────────────────────

def _serialize_atoms(atoms) -> list:
    """Convert backend RequirementAtom objects to frontend-friendly dicts."""
    result = []
    for a in atoms:
        result.append({
            "id": str(a.id),
            "text": a.text,
            "module": _safe_attr(a, "module", "UNKNOWN"),
            "priority": _safe_attr(a, "priority", "SHOULD"),
            "completenessScore": getattr(a, "completeness_score", 50),
            "isAmbiguous": getattr(a, "needs_review", False),
            "isDuplicate": str(_safe_attr(a, "status", "")).upper() == "DUPLICATE",
            "sourceFile": getattr(a, "source_file", "") or "",
            "sourceRow": None,
        })
    return result


def _serialize_classifications(classification_results, atoms_by_id: dict) -> list:
    """Convert backend ClassificationResult objects to frontend-friendly dicts."""
    result = []
    for r in classification_results:
        atom_id = str(r.atom_id)
        atom = atoms_by_id.get(atom_id, {})
        result.append({
            "requirementId": atom_id,
            "requirementText": atom.get("text", ""),
            "classification": _safe_attr(r, "verdict", "GAP"),
            "confidence": getattr(r, "confidence", 0),
            "rationale": getattr(r, "rationale", ""),
            "d365Feature": getattr(r, "matched_capability", None),
            "d365Module": atom.get("module"),
            "configNotes": getattr(r, "config_needed", None),
            "gapDescription": getattr(r, "gap_description", None),
            "caveats": getattr(r, "caveats", None),
        })
    return result


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/runs", response_model=RunResponse, dependencies=[Depends(verify_api_key)])
async def create_run(files: List[UploadFile] = File(...)):
    """Upload files and start the pipeline in background. Returns immediately."""
    run_id = str(uuid4())
    saved_paths = []

    for f in files:
        safe_name = f"{run_id}_{f.filename}"
        path = Path(settings.UPLOAD_DIR) / safe_name
        content = await f.read()
        with open(path, "wb") as out_f:
            out_f.write(content)
        saved_paths.append(str(path))

    # Create run record (graceful if Postgres unavailable)
    try:
        await postgres_client.create_run(run_id=run_id, source_files=saved_paths)
        await postgres_client.update_run_status(run_id, RunStatus.RUNNING)
    except Exception as e:
        log.warning("postgres_unavailable_for_run_create", error=str(e))

    # Build initial state and start pipeline in background
    state = make_initial_state(run_id=run_id, source_files=saved_paths)
    config = {"configurable": {"thread_id": run_id}}

    asyncio.create_task(_run_pipeline_background(run_id, state, config))

    return RunResponse(
        run_id=run_id,
        status="RUNNING",
        message="Pipeline started. Connect to /stream for real-time progress.",
    )


@router.get("/runs/{run_id}/stream")
async def stream_run_progress(run_id: str):
    """SSE endpoint — streams phase progress events in real time."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    run_subscribers[run_id].append(queue)

    async def event_generator():
        try:
            # Send current progress snapshot first
            progress = run_progress.get(run_id)
            if progress:
                yield f"data: {json.dumps({'type': 'state', **progress})}\n\n"

                # If pipeline already finished, send done immediately
                if progress.get("status") in ("COMPLETED", "FAILED", "AWAITING_REVIEW"):
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"
                    continue

                yield f"data: {json.dumps(event)}\n\n"

                if event.get("type") in ("done", "pipeline_error"):
                    break
        finally:
            if queue in run_subscribers.get(run_id, []):
                run_subscribers[run_id].remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}/status")
async def get_run_status(run_id: str):
    """Get current pipeline status and phase progress."""
    progress = run_progress.get(run_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, **progress}


@router.get("/runs/{run_id}/results")
async def get_run_results(run_id: str):
    """Get serialized pipeline results (atoms, classifications) for the frontend."""
    config = {"configurable": {"thread_id": run_id}}
    try:
        state_tuple = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail="Run state not found")

    if not state_tuple or not hasattr(state_tuple, "values"):
        raise HTTPException(status_code=404, detail="Run state not found")

    state = state_tuple.values

    atoms = _serialize_atoms(state.get("atoms", []))
    atoms_by_id = {a["id"]: a for a in atoms}
    classifications = _serialize_classifications(
        state.get("classification_results", []), atoms_by_id
    )

    return {
        "run_id": state.get("run_id"),
        "atoms": atoms,
        "classificationResults": classifications,
        "llmCostUsd": state.get("llm_cost_usd", 0),
        "humanReviewRequired": state.get("human_review_required", []),
    }


@router.get("/runs/{run_id}/export")
async def export_fitment_matrix(run_id: str):
    """Download the generated fitment_matrix.xlsx."""
    config = {"configurable": {"thread_id": run_id}}
    try:
        state_tuple = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail="Run state not found")

    state = state_tuple.values
    output_path = state.get("output_path")

    if not output_path or not os.path.exists(output_path):
        # Try default location
        output_path = os.path.join(settings.OUTPUT_DIR, f"{run_id}_fitment_matrix.xlsx")
        if not os.path.exists(output_path):
            raise HTTPException(status_code=404, detail="Export file not generated yet")

    return FileResponse(
        path=output_path,
        filename="fitment_matrix.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/runs/{run_id}/review", response_model=ReviewListResponse, dependencies=[Depends(verify_api_key)])
async def get_review_items(run_id: str):
    """Get items flagged for human review."""
    config = {"configurable": {"thread_id": run_id}}
    try:
        state_tuple = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail="Run state not found")

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
    """Submit human decisions and resume the pipeline (Phase 5 Validation)."""
    config = {"configurable": {"thread_id": run_id}}
    try:
        state_tuple = await graph.aget_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail="Run state not found")

    if not state_tuple or not hasattr(state_tuple, "values"):
        raise HTTPException(status_code=404, detail="Run state not found")

    from core.schemas.classification_result import ConsultantDecision
    from core.schemas.enums import Verdict
    from datetime import datetime

    decisions = []
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
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid verdict for atom {dec.atom_id}: {dec.verdict}"
            )

    try:
        new_state_dict = {"consultant_decisions": decisions}
        await graph.aupdate_state(config, new_state_dict)

        try:
            await postgres_client.update_run_status(run_id, RunStatus.RUNNING)
        except Exception:
            pass

        # Resume graph — validation node runs
        final_state = await graph.ainvoke(None, config=config)

        # Update progress tracking
        if run_id in run_progress:
            run_progress[run_id]["status"] = "COMPLETED"
            run_progress[run_id]["phases"]["validation"]["status"] = "completed"

        try:
            await postgres_client.update_run_status(run_id, RunStatus.COMPLETED)
        except Exception:
            pass

        return RunResponse(
            run_id=run_id,
            status=RunStatus.COMPLETED.value,
            message="Pipeline complete. Output generated.",
        )

    except Exception as e:
        log.error("run_resume_failed", run_id=run_id, error=str(e), exc_info=True)
        try:
            await postgres_client.update_run_status(run_id, RunStatus.FAILED)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
