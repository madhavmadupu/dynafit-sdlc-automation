"""
agents/ingestion/normalizer.py
Deduplication and terminology normalization for PartialAtom objects.
Uses RapidFuzz for dedup and module YAML canonical term maps for alignment.
"""

from __future__ import annotations

import re
from pathlib import Path

import structlog
import yaml
from rapidfuzz import fuzz

from agents.ingestion.req_extractor import PartialAtom
from core.schemas.enums import MoSCoW

log = structlog.get_logger()

# MoSCoW signal patterns
_MOSCOW_PATTERNS: dict[MoSCoW, list[str]] = {
    MoSCoW.MUST: [
        r"\bmust\b",
        r"\bmandatory\b",
        r"\brequired\b",
        r"\bcritical\b",
        r"\bshall\b",
        r"\bessential\b",
        r"\bnon-negotiable\b",
    ],
    MoSCoW.COULD: [
        r"\bnice to have\b",
        r"\boptional\b",
        r"\bif possible\b",
        r"\bcould\b",
        r"\bwould be good\b",
    ],
    MoSCoW.WONT: [
        r"\bout of scope\b",
        r"\bexcluded\b",
        r"\bnot in scope\b",
        r"\bwon['']?t\b",
        r"\bwill not\b",
    ],
    MoSCoW.SHOULD: [
        r"\bshould\b",
        r"\bexpected\b",
        r"\bneeds to\b",
        r"\bneed to\b",
        r"\bneeded\b",
    ],
}

# Module config cache
_module_configs: dict[str, dict] = {}


def _load_module_config(module: str) -> dict:
    """Load and cache YAML config for a D365 module."""
    if module in _module_configs:
        return _module_configs[module]

    config_dir = Path(__file__).parents[2] / "core" / "config" / "module_config"
    yaml_path = config_dir / f"{module.lower()}.yaml"

    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        _module_configs[module] = config or {}
    else:
        _module_configs[module] = {}

    return _module_configs[module]


def normalize_atoms(atoms: list[PartialAtom]) -> list[PartialAtom]:
    """
    Normalize a list of PartialAtoms:
    1. Apply MoSCoW priority enrichment from raw text signals
    2. Apply canonical term alignment from module YAML configs
    3. Deduplicate near-identical atoms within the same module

    Args:
        atoms: Raw PartialAtom list from req_extractor

    Returns:
        Deduplicated, term-aligned, priority-tagged PartialAtom list
    """
    if not atoms:
        return []

    # Step 1: MoSCoW enrichment
    enriched = [_enrich_moscow(atom) for atom in atoms]

    # Step 2: Term alignment
    aligned = [_align_terms(atom) for atom in enriched]

    # Step 3: Deduplication (within same module)
    deduped = _deduplicate(aligned)

    log.info(
        "normalization_complete",
        input=len(atoms),
        after_dedup=len(deduped),
        removed=len(atoms) - len(deduped),
    )
    return deduped


def _enrich_moscow(atom: PartialAtom) -> PartialAtom:
    """
    Override priority from raw_text signals only if current priority is SHOULD (default).
    Explicit priorities set by LLM are preserved.
    """
    if atom.priority != MoSCoW.SHOULD.value:
        return atom  # Preserve explicit LLM-assigned priority

    text_lower = atom.raw_text.lower()

    # Check in priority order: MUST > WONT > COULD > SHOULD(unchanged)
    for priority_enum in [MoSCoW.MUST, MoSCoW.WONT, MoSCoW.COULD]:
        patterns = _MOSCOW_PATTERNS[priority_enum]
        if any(re.search(pattern, text_lower) for pattern in patterns):
            # Return a copy with updated priority
            atom.__dict__["priority"] = priority_enum.value
            return atom

    return atom


def _align_terms(atom: PartialAtom) -> PartialAtom:
    """
    Map business jargon to D365 canonical terminology using module YAML.
    Case-insensitive word-boundary replacement.
    """
    config = _load_module_config(atom.module)
    canonical_terms: dict[str, str] = config.get("canonical_terms", {})

    if not canonical_terms:
        return atom

    normalized_text = atom.text
    for jargon, canonical in canonical_terms.items():
        # Word-boundary replacement, case-insensitive
        pattern = r"(?i)\b" + re.escape(jargon) + r"\b"
        normalized_text = re.sub(pattern, canonical, normalized_text)

    if normalized_text != atom.text:
        atom.__dict__["text"] = normalized_text

    return atom


def _deduplicate(atoms: list[PartialAtom]) -> list[PartialAtom]:
    """
    Remove near-duplicate atoms within the same module.
    Uses RapidFuzz token_sort_ratio > 90 as duplicate threshold.
    On collision, keeps the atom with higher completeness_score.
    """
    # Group by module
    by_module: dict[str, list[PartialAtom]] = {}
    for atom in atoms:
        by_module.setdefault(atom.module, []).append(atom)

    result: list[PartialAtom] = []
    total_deduped = 0

    for module, module_atoms in by_module.items():
        unique: list[PartialAtom] = []
        for candidate in module_atoms:
            is_duplicate = False
            for i, existing in enumerate(unique):
                similarity = fuzz.token_sort_ratio(candidate.text.lower(), existing.text.lower())
                if similarity > 90:
                    is_duplicate = True
                    # Keep the one with higher completeness_score
                    if candidate.completeness_score > existing.completeness_score:
                        unique[i] = candidate
                        log.debug(
                            "normalization_dedup",
                            module=module,
                            kept=candidate.text[:60],
                            dropped=existing.text[:60],
                            similarity=similarity,
                        )
                    else:
                        log.debug(
                            "normalization_dedup",
                            module=module,
                            kept=existing.text[:60],
                            dropped=candidate.text[:60],
                            similarity=similarity,
                        )
                    total_deduped += 1
                    break

            if not is_duplicate:
                unique.append(candidate)

        result.extend(unique)

    if total_deduped:
        log.info("normalization_dedup", total_removed=total_deduped)

    return result
