"""
Stage 5 — BDT Field Extraction Orchestrator

Ties together the three sub-stages:
  5a — Bond Anchor (regex, no LLM)
  5b — Grouped LLM Extraction (via LLMBackend)
  5c — Deterministic Post-processing

Single public function: extract_bond().
"""

from __future__ import annotations

import logging

from pipeline.llm_backend import LLMBackend, OllamaBackend
from pipeline.stage4_table import TableDetectionResult
from pipeline.stage5a_anchor import BondAnchor, extract_anchor
from pipeline.stage5b_llm import RawExtractionResult, extract_fields
from pipeline.stage5c_post import ExtractionResult, post_process

logger = logging.getLogger(__name__)


def extract_bond(
    table_result: TableDetectionResult,
    backend: LLMBackend | None = None,
) -> ExtractionResult:
    """
    Run the full Stage 5 pipeline for one bond section.

    Args:
        table_result: Output from Stage 4 (table detection).
        backend: LLM backend to use for field extraction. Defaults to
            OllamaBackend() (localhost:11434) if None.

    Returns:
        ExtractionResult with normalized fields and validation status.
        If no ISINs are found in 5a, returns done_partial immediately
        without making any LLM calls.
    """
    # 5a — Bond Anchor
    anchor = extract_anchor(table_result)
    logger.info(
        "Anchor: bond_name=%r, isins=%s",
        anchor.bond_name,
        anchor.isins,
    )

    if not anchor.isins:
        logger.warning("No valid ISINs found — returning done_partial without LLM calls")
        return ExtractionResult(
            anchor_bond_name=anchor.bond_name,
            anchor_isins=[],
            fields={},
            status="done_partial",
            warnings=[],
            manufacturer_target_market=["NOT_APPLICABLE"],
        )

    # 5b — Grouped LLM Extraction
    raw = extract_fields(table_result, anchor, backend)
    logger.info(
        "LLM extraction: %d groups extracted, %d errors",
        len(raw.groups),
        len(raw.errors),
    )

    # 5c — Deterministic Post-processing
    result = post_process(raw)
    logger.info("Post-processing: status=%s, %d warnings", result.status, len(result.warnings))

    return result
