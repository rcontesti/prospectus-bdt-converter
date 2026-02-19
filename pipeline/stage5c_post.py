"""
Stage 5c — Deterministic Post-processing

Normalizes and validates LLM extraction results.  No interpretation —
only deterministic transformations: date parsing, amount formatting,
ISIN checksum validation, enum validation, LEI resolution, and
manufacturer target market derivation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx
from dateutil import parser as dateparser

from bdt import enums
from pipeline.stage5a_anchor import _isin_checksum_valid
from pipeline.stage5b_llm import RawExtractionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ValidationWarning:
    """A single validation issue found during post-processing."""

    field_name: str
    group: str
    message: str
    raw_value: str | None = None


@dataclass
class PartyInfo:
    """A deal party with optional LEI."""

    name: str
    role: str
    lei: str | None = None
    lei_resolved: bool = False


@dataclass
class ExtractionResult:
    """Final result of Stage 5 extraction for one bond."""

    anchor_bond_name: str
    anchor_isins: list[str]
    fields: dict  # flat dict of all normalized field values
    parties: list[PartyInfo] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)
    status: str = "done_valid"  # "done_valid" or "done_partial"
    manufacturer_target_market: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Enum lookup: field name → allowed values list
# ---------------------------------------------------------------------------

_ENUM_FIELDS: dict[str, list[str]] = {
    "interest_type": enums.INTEREST_TYPE,
    "interest_payment_frequency": enums.INTEREST_PAYMENT_FREQUENCY,
    "day_count_fraction": enums.DAY_COUNT_FRACTION,
    "business_day_convention": enums.BUSINESS_DAY_CONVENTION,
    "business_day_center": enums.BUSINESS_DAY_CENTER,
    "issuance_type": enums.ISSUANCE_TYPE,
    "form_of_note": enums.FORM_OF_NOTE,
    "status_of_note": enums.STATUS_OF_NOTE,
    "governing_law": enums.GOVERNING_LAW,
    "redemption_payment_basis": enums.REDEMPTION_PAYMENT_BASIS,
}

# Fields that are dates and should be normalized to ISO 8601
_DATE_FIELDS = {
    "pricing_date",
    "issue_date",
    "settlement_date",
    "maturity_date",
    "interest_commencement_date",
    "first_interest_payment_date",
}

# Fields that are numeric amounts
_AMOUNT_FIELDS = {
    "aggregate_nominal_amount",
    "specified_denomination",
    "integral_multiples",
    "issue_price",
    "interest_rate",
}

# Required fields for a "done_valid" status
_REQUIRED_FIELDS = {
    "issuance_type",
    "specified_denomination",
    "specified_currency",
    "pricing_date",
    "issue_date",
    "settlement_date",
    "issue_price",
    "governing_law",
    "form_of_note",
    "status_of_note",
    "aggregate_nominal_amount",
    "maturity_date",
    "interest_type",
    "interest_commencement_date",
    "interest_payment_frequency",
    "day_count_fraction",
    "business_day_convention",
    "business_day_center",
}


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def normalize_date(
    value: str | None, field_name: str
) -> tuple[str | None, ValidationWarning | None]:  # noqa: E501
    """Parse a date string into ISO 8601 (YYYY-MM-DD)."""
    if value is None or str(value).strip() == "":
        return None, None
    try:
        dt = dateparser.parse(str(value))
        return dt.strftime("%Y-%m-%d"), None
    except (ValueError, TypeError):
        return None, ValidationWarning(
            field_name=field_name,
            group="dates",
            message=f"Cannot parse date: '{value}'",
            raw_value=str(value),
        )


def normalize_amount(
    value: str | float | None, field_name: str
) -> tuple[float | None, ValidationWarning | None]:  # noqa: E501
    """Strip currency symbols and parse to float."""
    if value is None:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    # Remove currency symbols, commas, spaces, and common prefixes
    cleaned = re.sub(r"[US$€£¥,\s]", "", raw)
    # Handle percentage notation for rates (e.g., "5.5%")
    if "%" in cleaned:
        cleaned = cleaned.replace("%", "")
        try:
            return float(cleaned) / 100, None
        except ValueError:
            pass
    try:
        return float(cleaned), None
    except ValueError:
        return None, ValidationWarning(
            field_name=field_name,
            group="amounts",
            message=f"Cannot parse amount: '{value}'",
            raw_value=str(value),
        )


def validate_isin(isin: str) -> bool:
    """Validate a 12-character ISIN with ISO 6166 checksum."""
    return _isin_checksum_valid(isin)


def validate_enum(
    value: str | None,
    field_name: str,
    allowed: list[str],
) -> tuple[str | None, ValidationWarning | None]:
    """Validate that a value is in the allowed enum list."""
    if value is None:
        return None, None
    upper = str(value).strip().upper()
    # Try exact match first
    if upper in allowed:
        return upper, None
    # Try replacing spaces/hyphens with underscores
    normalized = re.sub(r"[\s\-]+", "_", upper)
    if normalized in allowed:
        return normalized, None
    return None, ValidationWarning(
        field_name=field_name,
        group="enum",
        message=f"Value '{value}' not in allowed list: {allowed}",
        raw_value=str(value),
    )


# ---------------------------------------------------------------------------
# GLEIF LEI resolution
# ---------------------------------------------------------------------------

# Module-level cache to avoid repeated API calls in a single run
_lei_cache: dict[str, str | None] = {}

_GLEIF_BASE = "https://api.gleif.org/api/v1/fuzzycompletions"
_GLEIF_TIMEOUT = 10.0


def resolve_lei(
    party_name: str,
    http_client: httpx.Client | None = None,
) -> str | None:
    """
    Resolve a party name to a LEI via the GLEIF fuzzycompletions API.

    Returns the LEI string or None if not found / API unavailable.
    Results are cached per-run.
    """
    if party_name in _lei_cache:
        return _lei_cache[party_name]

    try:
        client = http_client or httpx.Client(timeout=_GLEIF_TIMEOUT)
        response = client.get(_GLEIF_BASE, params={"field": "fullName", "q": party_name})
        response.raise_for_status()
        data = response.json()

        completions = data.get("data", [])
        if completions:
            lei = (
                completions[0]
                .get("relationships", {})
                .get("lei-records", {})
                .get("data", {})
                .get("id")
            )  # noqa: E501
            if not lei:
                # Alternative structure
                attrs = completions[0].get("attributes", {})
                lei = attrs.get("lei")
            _lei_cache[party_name] = lei
            return lei
    except (httpx.HTTPError, KeyError, IndexError):
        logger.debug("GLEIF lookup failed for '%s'", party_name)
    finally:
        if http_client is None and "client" in locals():
            client.close()

    _lei_cache[party_name] = None
    return None


def clear_lei_cache() -> None:
    """Clear the module-level LEI cache (useful between test runs)."""
    _lei_cache.clear()


# ---------------------------------------------------------------------------
# Target market derivation
# ---------------------------------------------------------------------------


def derive_target_market(selling_restrictions: list[str] | None) -> list[str]:
    """
    Derive ManufacturerTargetMarket from selling restrictions.

    Rule from CLAUDE.md: if SellingRestrictions contains 144A or REGS_CAT2
    but no EU/UK MiFID restriction, set NOT_APPLICABLE.
    """
    if not selling_restrictions:
        return ["NOT_APPLICABLE"]

    restrictions_upper = [r.upper() for r in selling_restrictions]

    has_us_restriction = "144A" in restrictions_upper or "REGS_CAT2" in restrictions_upper
    has_eu_mifid = any("MIFID" in r or "MIFIR" in r for r in restrictions_upper)

    if has_us_restriction and not has_eu_mifid:
        return ["NOT_APPLICABLE"]

    # Default: return NOT_APPLICABLE (conservative — Stage 6 can override)
    return ["NOT_APPLICABLE"]


# ---------------------------------------------------------------------------
# Main post-processing function
# ---------------------------------------------------------------------------


def post_process(raw: RawExtractionResult) -> ExtractionResult:
    """
    Post-process raw LLM extraction results into normalized, validated fields.

    Steps:
    1. Flatten all group dicts into a single fields dict.
    2. Normalize date fields → ISO 8601.
    3. Normalize amount fields → float.
    4. Validate ISINs from anchor.
    5. Validate enum fields against allowed lists.
    6. Extract party information.
    7. Derive ManufacturerTargetMarket.
    8. Check required fields → set status.

    Args:
        raw: Output from Stage 5b.

    Returns:
        ExtractionResult with normalized fields and validation status.
    """
    warnings: list[ValidationWarning] = []
    flat_fields: dict = {}

    # Step 1: Flatten
    for _group_name, group_result in raw.groups.items():
        for k, v in group_result.fields.items():
            flat_fields[k] = v

    # Step 2: Normalize dates
    for date_field in _DATE_FIELDS:
        if date_field in flat_fields:
            value, warning = normalize_date(flat_fields[date_field], date_field)
            flat_fields[date_field] = value
            if warning:
                warnings.append(warning)

    # Step 3: Normalize amounts
    for amount_field in _AMOUNT_FIELDS:
        if amount_field in flat_fields:
            value, warning = normalize_amount(flat_fields[amount_field], amount_field)
            flat_fields[amount_field] = value
            if warning:
                warnings.append(warning)

    # Step 4: Validate ISINs
    for isin in raw.anchor.isins:
        if not validate_isin(isin):
            warnings.append(
                ValidationWarning(
                    field_name="isin",
                    group="identifiers",
                    message=f"ISIN '{isin}' failed checksum validation",
                    raw_value=isin,
                )
            )

    # Step 5: Validate enums
    for field_name, allowed in _ENUM_FIELDS.items():
        if field_name in flat_fields and flat_fields[field_name] is not None:
            value, warning = validate_enum(flat_fields[field_name], field_name, allowed)
            flat_fields[field_name] = value
            if warning:
                warnings.append(warning)

    # Step 6: Extract parties
    parties = _extract_parties(flat_fields)

    # Step 7: Selling restrictions → target market
    selling_restrictions = flat_fields.get("selling_restrictions")
    if isinstance(selling_restrictions, str):
        selling_restrictions = [selling_restrictions]
    target_market = derive_target_market(selling_restrictions)

    # Step 8: Check required fields
    missing = [f for f in _REQUIRED_FIELDS if not flat_fields.get(f)]
    status = "done_valid" if not missing else "done_partial"

    if missing:
        warnings.append(
            ValidationWarning(
                field_name="__required__",
                group="validation",
                message=f"Missing required fields: {', '.join(sorted(missing))}",
            )
        )

    return ExtractionResult(
        anchor_bond_name=raw.anchor.bond_name,
        anchor_isins=raw.anchor.isins,
        fields=flat_fields,
        parties=parties,
        warnings=warnings,
        status=status,
        manufacturer_target_market=target_market,
    )


def _extract_parties(flat_fields: dict) -> list[PartyInfo]:
    """Build PartyInfo list from flat fields."""
    parties: list[PartyInfo] = []

    _add_party(parties, flat_fields, "issuer_name", "ISSUER")
    _add_party(parties, flat_fields, "guarantor_name", "GUARANTOR")
    _add_party(parties, flat_fields, "trustee", "TRUSTEE")
    _add_party(parties, flat_fields, "fiscal_agent", "FISCAL_AGENT")
    _add_party(parties, flat_fields, "principal_paying_agent", "PRINCIPAL_PAYING_AGENT")

    # Lead managers can be a list
    managers = flat_fields.get("lead_managers")
    if managers:
        if isinstance(managers, str):
            managers = [managers]
        for name in managers:
            if name and str(name).strip():
                parties.append(PartyInfo(name=str(name).strip(), role="JOINT_LEAD_MANAGER"))

    return parties


def _add_party(
    parties: list[PartyInfo],
    fields: dict,
    field_name: str,
    role: str,
) -> None:
    """Add a single party if the field is present and non-null."""
    value = fields.get(field_name)
    if value and str(value).strip():
        parties.append(PartyInfo(name=str(value).strip(), role=role))
