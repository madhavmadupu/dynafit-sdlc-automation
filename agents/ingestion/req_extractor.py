"""
agents/ingestion/req_extractor.py
LLM-based requirement atomization.
Converts RawChunk objects into PartialAtom dictionaries via the ingestion_extract.j2 prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from agents.ingestion.doc_parser import RawChunk
from core.config.settings import settings
from core.schemas.enums import D365Module, IntentType, MoSCoW
from infrastructure.llm.client import llm_call

log = structlog.get_logger()

BATCH_SIZE = 20  # Max chunks per LLM call to avoid token limits

# Load Jinja2 environment
_jinja_env: Environment | None = None


def _get_jinja_env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        import pathlib

        prompts_dir = str(pathlib.Path(__file__).parents[2] / "core" / "prompts")
        _jinja_env = Environment(
            loader=FileSystemLoader(prompts_dir),
            autoescape=select_autoescape([]),  # No HTML escaping for prompt templates
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _jinja_env


@dataclass
class PartialAtom:
    """Unnormalized, unvalidated atom from LLM extraction. Pre-schema form."""

    text: str
    raw_text: str
    module: str
    sub_module: str | None
    priority: str
    intent: str
    country: str | None
    completeness_score: float
    source_ref: str
    source_file: str = ""


async def extract_atoms_from_chunks(
    chunks: list[RawChunk],
    run_id: str,
    rejection_reason: str = "",
    retry_count: int = 0,
) -> list[PartialAtom]:
    """
    Extract atomic requirements from raw document chunks using LLM.

    Processes chunks in batches of up to BATCH_SIZE per LLM call to respect token limits.

    Args:
        chunks: Raw text chunks from doc_parser
        run_id: Pipeline run ID for logging/tracing
        rejection_reason: If non-empty, injected into prompt as retry context
        retry_count: Current retry attempt number

    Returns:
        List of PartialAtom objects (may be more than input chunks due to splitting)
    """
    if not chunks:
        return []

    all_atoms: list[PartialAtom] = []

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        batch_atoms = await _extract_batch(
            batch=batch,
            run_id=run_id,
            rejection_reason=rejection_reason,
            retry_count=retry_count,
        )
        all_atoms.extend(batch_atoms)

    log.info(
        "ingestion.extracted",
        run_id=run_id,
        input_chunks=len(chunks),
        output_atoms=len(all_atoms),
    )
    return all_atoms


async def _extract_batch(
    batch: list[RawChunk],
    run_id: str,
    rejection_reason: str,
    retry_count: int,
) -> list[PartialAtom]:
    """Process a single batch of chunks with one LLM call."""
    # Combine batch into single prompt
    combined_text = "\n\n---\n\n".join(f"[{chunk.source_ref}]\n{chunk.text}" for chunk in batch)
    source_ref = batch[0].source_ref if len(batch) == 1 else f"{batch[0].source_file}:batch"
    source_file = batch[0].source_file

    env = _get_jinja_env()
    template = env.get_template("ingestion_extract.j2")
    prompt_text = template.render(
        chunk_text=combined_text,
        source_ref=source_ref,
        rejection_reason=rejection_reason,
        retry_count=retry_count,
    )

    messages = [
        {"role": "user", "content": prompt_text},
    ]

    try:
        response = await llm_call(
            messages=messages,
            model=settings.INGESTION_MODEL,
            trace_name="ingestion_extract",
            run_id=run_id,
        )
        return _parse_llm_response(response.content, source_file, batch)
    except Exception as e:
        log.error(
            "extraction_batch_failed",
            run_id=run_id,
            source_ref=source_ref,
            error=str(e),
            exc_info=True,
        )
        return []


def _parse_llm_response(content: str, source_file: str, batch: list[RawChunk]) -> list[PartialAtom]:
    """Parse LLM JSON response into PartialAtom list."""
    # Strip any accidental markdown fences
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        raw_atoms = json.loads(cleaned)
        if not isinstance(raw_atoms, list):
            raise ValueError("LLM response is not a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        log.error("extraction_json_parse_failed", error=str(e), content_preview=content[:200])
        return []

    atoms: list[PartialAtom] = []
    for item in raw_atoms:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text or len(text) < 5:
            continue

        # Normalize module to valid enum
        module_str = str(item.get("module", "UNKNOWN")).upper().strip()
        if module_str not in {m.value for m in D365Module}:
            module_str = "UNKNOWN"

        # Normalize priority
        priority_str = str(item.get("priority", "SHOULD")).upper().strip()
        if priority_str not in {m.value for m in MoSCoW}:
            priority_str = "SHOULD"

        # Normalize intent
        intent_str = str(item.get("intent", "FUNCTIONAL")).upper().strip()
        if intent_str not in {m.value for m in IntentType}:
            intent_str = "FUNCTIONAL"

        # Clamp completeness_score
        try:
            completeness = float(item.get("completeness_score", 50))
            completeness = max(0.0, min(100.0, completeness))
        except (TypeError, ValueError):
            completeness = 50.0

        # Country normalization
        country = item.get("country")
        if country and (not isinstance(country, str) or len(country) != 2):
            country = None

        atoms.append(
            PartialAtom(
                text=text,
                raw_text=str(item.get("raw_text", text)),
                module=module_str,
                sub_module=item.get("sub_module"),
                priority=priority_str,
                intent=intent_str,
                country=str(country).upper() if country else None,
                completeness_score=completeness,
                source_ref=str(item.get("source_ref", batch[0].source_ref if batch else "")),
                source_file=source_file,
            )
        )

    return atoms
