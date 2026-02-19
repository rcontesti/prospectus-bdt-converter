"""
Stage 5b — Grouped LLM Extraction

Sends one prompt per field group to the LLM backend, with JSON output expected.
Each prompt includes the ISIN anchor and the enum values inline, so the LLM maps
prospectus text → BDT field values directly.

The backend is injected via the LLMBackend protocol — any provider can be used
without changing this module.  Each group is extracted independently; one failure
does not block others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bdt.enums import AMORTIZATION_FIELDS, FIELD_GROUPS
from pipeline.llm_backend import LLMBackend, OllamaBackend
from pipeline.stage4_table import TableDetectionResult
from pipeline.stage5a_anchor import BondAnchor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AMORTIZATION_KEYWORDS = [
    "amortiz",
    "installment",
    "repayment schedule",
    "principal repayment",
    "scheduled redemption",
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class GroupExtractionResult:
    """Result of extracting one field group."""

    group_name: str
    fields: dict  # field_name → raw_value
    raw_response: str = ""
    model: str = ""


@dataclass
class RawExtractionResult:
    """Result of extracting all field groups for one bond."""

    anchor: BondAnchor
    groups: dict[str, GroupExtractionResult] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_system_prompt(anchor: BondAnchor) -> str:
    """Build the system prompt with ISIN anchor."""
    isin_clause = ""
    if anchor.isins:
        isins_str = ", ".join(anchor.isins)
        isin_clause = (
            f"\nThe bond you are extracting data for has ISIN(s): {isins_str}. "
            f"Only extract information about THIS bond. "
            f"Ignore all other bonds or ISINs mentioned in the text."
        )

    return (
        "You are a bond data extraction assistant. "
        "You extract structured financial data from bond prospectus text. "
        "Return ONLY valid JSON with the requested fields. "
        "If a field is not found in the text, return null for that field. "
        "Do not guess or hallucinate values — only extract what is explicitly stated."
        f"{isin_clause}"
    )


def _build_group_prompt(
    group_name: str,
    group_def: dict,
    table_text: str,
    anchor: BondAnchor,
) -> str:
    """Build the user prompt for a single field group."""
    fields_desc = "\n".join(
        f'  - "{k}": {v}' for k, v in group_def["fields"].items()
    )

    isin_ref = ""
    if anchor.isins:
        isin_ref = f" for the bond with ISIN {anchor.isins[0]}"

    return (
        f"Extract the following {group_def['description']}{isin_ref} "
        f"from the bond prospectus text below.\n\n"
        f"Fields to extract:\n{fields_desc}\n\n"
        f"Return a JSON object with exactly these keys.\n\n"
        f"--- PROSPECTUS TEXT ---\n{table_text}"
    )


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------


def _should_extract_amortization(
    table_text: str,
    issuance_result: GroupExtractionResult | None,
) -> bool:
    """Determine if amortization extraction should run."""
    text_lower = table_text.lower()
    if any(kw in text_lower for kw in _AMORTIZATION_KEYWORDS):
        return True
    if issuance_result and issuance_result.fields:
        rpb = issuance_result.fields.get("redemption_payment_basis", "")
        if rpb and str(rpb).upper() == "INSTALLMENT":
            return True
    return False


def extract_fields(
    table_result: TableDetectionResult,
    anchor: BondAnchor,
    backend: LLMBackend | None = None,
) -> RawExtractionResult:
    """
    Extract all BDT field groups for one bond via the LLM backend.

    Each group is extracted independently.  Failures are recorded in
    the errors list but do not abort remaining groups.

    Args:
        table_result: Output from Stage 4.
        anchor: Output from Stage 5a.
        backend: LLM backend to use. Defaults to OllamaBackend() if None.

    Returns:
        RawExtractionResult with one GroupExtractionResult per group.
    """
    if backend is None:
        backend = OllamaBackend()

    result = RawExtractionResult(anchor=anchor)
    system_prompt = _build_system_prompt(anchor)
    text = table_result.table_text

    # Extract standard groups
    for group_name, group_def in FIELD_GROUPS.items():
        try:
            user_prompt = _build_group_prompt(group_name, group_def, text, anchor)
            fields = backend.complete(system_prompt, user_prompt)
            result.groups[group_name] = GroupExtractionResult(
                group_name=group_name,
                fields=fields,
                model=getattr(backend, "model", "unknown"),
            )
        except RuntimeError as exc:
            logger.warning("Group '%s' extraction failed: %s", group_name, exc)
            result.errors.append(f"{group_name}: {exc}")
            result.groups[group_name] = GroupExtractionResult(
                group_name=group_name,
                fields={},
            )

    # Conditional amortization extraction
    issuance_group = result.groups.get("issuance")
    if _should_extract_amortization(text, issuance_group):
        try:
            user_prompt = _build_group_prompt(
                "amortization", AMORTIZATION_FIELDS, text, anchor
            )
            fields = backend.complete(system_prompt, user_prompt)
            result.groups["amortization"] = GroupExtractionResult(
                group_name="amortization",
                fields=fields,
                model=getattr(backend, "model", "unknown"),
            )
        except RuntimeError as exc:
            logger.warning("Amortization extraction failed: %s", exc)
            result.errors.append(f"amortization: {exc}")

    return result
