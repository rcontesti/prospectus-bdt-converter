"""
Stage 6 — XML Assembly and XSD Validation.

Takes an ExtractionResult from Stage 5c and produces a BDT v1.2 compliant
XML document, then validates it against the ICMA XSD.

Output modes:
    done_valid   — all required fields present, XSD validation passes.
    done_partial — one or more required fields missing or XSD errors found;
                   XML is still written with available data plus a
                   ValidationWarnings comment block at the end.

The XSD enforces strict element ordering (xs:sequence) so every _build_*
function must add child elements in the exact order defined by the schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from lxml import etree

from pipeline.stage5c_post import ExtractionResult, PartyInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BDT_NS = "urn:icma:xsd:ICMABondDataTaxonomy"
_N = f"{{{BDT_NS}}}"  # shorthand: f"{_N}ElementName"

_XSD_DIR = Path(__file__).parent.parent / ".docs" / "ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02"

# LEIIdentifier XSD pattern: [A-Z0-9]{18}[0-9]{2}
_LEI_PATTERN = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
# CUSIPIdentifier XSD pattern: [0-9]{9} (digits only)
_CUSIP_PATTERN = re.compile(r"^[0-9]{9}$")
# COMMON_CODEIdentifier XSD pattern: [A-Z0-9]{9}
_COMMON_CODE_PATTERN = re.compile(r"^[A-Z0-9]{9}$")
# SEDOLIdentifier XSD pattern: [A-Z0-9]{6}[0-9]{1}
_SEDOL_PATTERN = re.compile(r"^[A-Z0-9]{6}[0-9]{1}$")

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class AssemblyResult:
    """Result of Stage 6 XML assembly for one bond."""

    xml_bytes: bytes
    filename: str
    xsd_valid: bool
    xsd_errors: list[str] = field(default_factory=list)
    status: str = "done_valid"
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def assemble(
    result: ExtractionResult,
    xsd_dir: Path | None = None,
) -> AssemblyResult:
    """
    Assemble a BDT v1.2 XML document from a post-processed ExtractionResult.

    Args:
        result:  ExtractionResult from Stage 5c.
        xsd_dir: Directory containing the ICMA XSD files.
                 Defaults to the bundled .docs/ directory.

    Returns:
        AssemblyResult with XML bytes, filename, XSD validity, and warnings.
    """
    asm_warnings: list[str] = []
    f = result.fields

    # Build party registry before writing any elements so PIDs are stable
    party_registry = _build_party_registry(result.parties)

    # Root element
    nsmap = {
        None: BDT_NS,
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }
    root = etree.Element(f"{_N}Document", nsmap=nsmap)
    root.set(
        "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
        f"{BDT_NS} icma-bond-data-taxonomy.xsd",
    )
    taxonomy = _sub(root, "ICMABondDataTaxonomy")

    # XSD sequence: PartyRole* → Party* → Issuance? → Product?
    _emit_party_roles(taxonomy, result.parties, party_registry, asm_warnings)
    _emit_parties(taxonomy, result.parties, party_registry, asm_warnings)
    _build_issuance(taxonomy, f, result.manufacturer_target_market, asm_warnings)
    _build_product(taxonomy, f, result.anchor_isins, asm_warnings)

    # Serialize
    xml_bytes = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    # Append ValidationWarnings comment for done_partial
    xsd_errors: list[str] = []
    xsd_valid = False
    resolved_xsd_dir = xsd_dir or _XSD_DIR
    if resolved_xsd_dir.exists():
        xsd_valid, xsd_errors = _validate_xsd(root, resolved_xsd_dir)
    else:
        asm_warnings.append(f"XSD directory not found: {resolved_xsd_dir}")

    status = result.status
    if not xsd_valid:
        status = "done_partial"

    if status == "done_partial":
        all_warnings = [w.message for w in result.warnings] + asm_warnings + xsd_errors
        comment_lines = ["", "ValidationWarnings:"]
        for w in all_warnings:
            comment_lines.append(f"  - {w}")
        comment_lines.append("")
        comment = etree.Comment("\n".join(comment_lines))
        xml_bytes += b"\n" + etree.tostring(comment)

    # Filename: primary ISIN or bond name
    primary_isin = result.anchor_isins[0] if result.anchor_isins else None
    filename = f"{primary_isin}.xml" if primary_isin else "bond.xml"

    return AssemblyResult(
        xml_bytes=xml_bytes,
        filename=filename,
        xsd_valid=xsd_valid,
        xsd_errors=xsd_errors,
        status=status,
        warnings=asm_warnings,
    )


# ---------------------------------------------------------------------------
# Party registry
# ---------------------------------------------------------------------------


def _build_party_registry(
    parties: list[PartyInfo],
) -> dict[str, tuple[str, str | None]]:
    """
    Build a mapping of party name → (pid, lei) for PID assignment.

    Deduplicates by name.  PID uses the real LEI when available and valid,
    otherwise a sequential placeholder.
    """
    registry: dict[str, tuple[str, str | None]] = {}
    counter = 0
    for party in parties:
        if party.name in registry:
            continue
        lei = party.lei if party.lei and _LEI_PATTERN.match(party.lei) else None
        pid = f"LEI-{lei}" if lei else f"PARTY-{counter}"
        if not lei:
            counter += 1
        registry[party.name] = (pid, lei)
    return registry


def _emit_party_roles(
    taxonomy: etree._Element,
    parties: list[PartyInfo],
    registry: dict[str, tuple[str, str | None]],
    warnings: list[str],
) -> None:
    """Emit one <PartyRole> element per party (including duplicates with different roles)."""
    if not parties:
        warnings.append("No parties extracted — at least one party required by XSD")
        # Emit a minimal placeholder so the document is structurally parseable
        role_elem = _sub(taxonomy, "PartyRole")
        _sub(role_elem, "PartyRoleType", "ISSUER")
        pid_elem = _sub(role_elem, "PartyID")
        pid_elem.set("PID", "PARTY-0")
        return

    for party in parties:
        pid, _ = registry[party.name]
        role_elem = _sub(taxonomy, "PartyRole")
        _sub(role_elem, "PartyRoleType", party.role)
        pid_elem = _sub(role_elem, "PartyID")
        pid_elem.set("PID", pid)


def _emit_parties(
    taxonomy: etree._Element,
    parties: list[PartyInfo],
    registry: dict[str, tuple[str, str | None]],
    warnings: list[str],
) -> None:
    """Emit one <Party> element per unique party (deduplicated)."""
    if not parties:
        # Placeholder already handled by _emit_party_roles; emit matching Party
        party_elem = etree.SubElement(taxonomy, f"{_N}Party")
        party_elem.set("PID", "PARTY-0")
        _sub(party_elem, "PartyName", "UNKNOWN")
        _sub(party_elem, "LEIIdentifier", "PLACEHOLDER")
        return

    seen_pids: set[str] = set()
    for party in parties:
        pid, lei = registry[party.name]
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        party_elem = etree.SubElement(taxonomy, f"{_N}Party")
        party_elem.set("PID", pid)
        _sub(party_elem, "PartyName", party.name)
        lei_val = lei if lei else "PLACEHOLDER"
        _sub(party_elem, "LEIIdentifier", lei_val)


# ---------------------------------------------------------------------------
# Issuance section
# ---------------------------------------------------------------------------


def _build_issuance(
    taxonomy: etree._Element,
    f: dict,
    manufacturer_target_market: list[str],
    warnings: list[str],
) -> None:
    """Build <Issuance> in strict XSD sequence order."""
    issuance = _sub(taxonomy, "Issuance")

    # Required
    _req(issuance, "IssuanceType", f.get("issuance_type"), warnings)
    _req(
        issuance, "SpecifiedDenomination", _fmt_decimal(f.get("specified_denomination")), warnings
    )  # noqa: E501

    # Optional
    if f.get("integral_multiples") is not None:
        _sub(issuance, "IntegralMultiples", _fmt_decimal(f["integral_multiples"]))

    # Required
    _req(issuance, "SpecifiedCurrency", f.get("specified_currency"), warnings)
    _req(issuance, "PricingDate", f.get("pricing_date"), warnings)
    _req(issuance, "IssueDate", f.get("issue_date"), warnings)
    _req(issuance, "SettlementDate", f.get("settlement_date"), warnings)
    _req(issuance, "IssuePrice", _fmt_decimal(f.get("issue_price")), warnings)

    # Listing (required 1+): use extracted listing or fall back to NOT_LISTED
    listing_market = f.get("listing_market")
    listing_elem = _sub(issuance, "Listing")
    _sub(listing_elem, "Market", listing_market if listing_market else "NOT_LISTED")

    # ClearingSettlementSystem (optional)
    clearing = f.get("clearing_settlement_systems")
    if clearing:
        if isinstance(clearing, str):
            clearing = [clearing]
        css_elem = _sub(issuance, "ClearingSettlementSystem")
        for system in clearing:
            _sub(css_elem, "ClearingSettlementSystem", system)

    # Required
    _req(issuance, "GoverningLaw", f.get("governing_law"), warnings)

    # SellingRestrictions (required 1+)
    restrictions = f.get("selling_restrictions")
    if isinstance(restrictions, str):
        restrictions = [restrictions]
    if not restrictions:
        restrictions = ["NOT_APPLICABLE"]
        warnings.append("No selling restrictions found; defaulting to NOT_APPLICABLE")
    sr_elem = _sub(issuance, "SellingRestrictions")
    for r in restrictions:
        _sub(sr_elem, "SellingRestriction", r)

    # PRIIPsRestriction (optional)
    priips = f.get("priips_restriction")
    if priips:
        _sub(issuance, "PRIIPsRestriction", priips)

    # ManufacturerTargetMarket (required 1+) — always present from stage5c
    if not manufacturer_target_market:
        manufacturer_target_market = ["NOT_APPLICABLE"]
    for mtm in manufacturer_target_market:
        _sub(issuance, "ManufacturerTargetMarket", mtm)

    # RedemptionPaymentBasis (optional) — set for amortizing bonds
    redemption_basis = f.get("redemption_payment_basis")
    if redemption_basis:
        _sub(issuance, "RedemptionPaymentBasis", redemption_basis)


# ---------------------------------------------------------------------------
# Product section
# ---------------------------------------------------------------------------


def _build_product(
    taxonomy: etree._Element,
    f: dict,
    anchor_isins: list[str],
    warnings: list[str],
) -> None:
    """Build <Product> in strict XSD sequence order."""
    product = _sub(taxonomy, "Product")

    # SecurityIdentifierList
    _build_identifier_list(product, f, anchor_isins, warnings)

    # Required product fields
    _req(product, "FormOfNote", f.get("form_of_note"), warnings)
    _req(product, "StatusOfNote", f.get("status_of_note"), warnings)
    _req(
        product,
        "AggregateNominalAmount",
        _fmt_decimal(f.get("aggregate_nominal_amount")),
        warnings,
    )  # noqa: E501
    _req(product, "MaturityDate", f.get("maturity_date"), warnings)

    # InterestPayment (required)
    _build_interest_payment(product, f, warnings)

    # Required
    _req(product, "DayCountFraction", f.get("day_count_fraction"), warnings)
    _req(product, "BusinessDayConvention", f.get("business_day_convention"), warnings)
    _req(product, "BusinessDayCenter", f.get("business_day_center"), warnings)


def _build_identifier_list(
    product: etree._Element,
    f: dict,
    anchor_isins: list[str],
    warnings: list[str],
) -> None:
    """Build <SecurityIdentifierList> from anchor ISINs and extracted identifiers."""
    id_list = _sub(product, "SecurityIdentifierList")

    # ISINs from anchor (authoritative)
    for isin in anchor_isins:
        si = _sub(id_list, "SecurityIdentifier")
        _sub(si, "ISIN", isin)
        _sub(si, "IdentifierType", "ISIN")

    # CUSIP — BDT pattern requires exactly 9 digits
    cusip = f.get("cusip")
    if cusip and _CUSIP_PATTERN.match(str(cusip)):
        si = _sub(id_list, "SecurityIdentifier")
        _sub(si, "CUSIP", cusip)
        _sub(si, "IdentifierType", "CUSIP")
    elif cusip:
        warnings.append(
            f"CUSIP '{cusip}' skipped — BDT requires exactly 9 digits (XSD pattern [0-9]{{9}})"
        )

    # Common Code — BDT pattern: 9 alphanumeric chars
    common_code = f.get("common_code")
    if common_code and _COMMON_CODE_PATTERN.match(str(common_code).upper()):
        si = _sub(id_list, "SecurityIdentifier")
        _sub(si, "COMMON_CODE", str(common_code).upper())
        _sub(si, "IdentifierType", "COMMON_CODE")
    elif common_code:
        warnings.append(f"Common Code '{common_code}' skipped — BDT requires 9 alphanumeric chars")

    # SEDOL — 7 chars: 6 alphanumeric + 1 digit
    sedol = f.get("sedol")
    if sedol and _SEDOL_PATTERN.match(str(sedol).upper()):
        si = _sub(id_list, "SecurityIdentifier")
        _sub(si, "SEDOL", str(sedol).upper())
        _sub(si, "IdentifierType", "SEDOL")


def _build_interest_payment(
    product: etree._Element,
    f: dict,
    warnings: list[str],
) -> None:
    """Build <InterestPayment> including <InterestPayments> sub-structure."""
    ip_elem = _sub(product, "InterestPayment")

    # Required
    _req(ip_elem, "InterestType", f.get("interest_type"), warnings)

    # InterestRate: stored as decimal fraction (0.055), BDT expects percentage (5.5)
    rate = f.get("interest_rate")
    if rate is not None:
        _sub(ip_elem, "InterestRate", _fmt_rate(rate))

    # Required
    _req(ip_elem, "InterestCommencementDate", f.get("interest_commencement_date"), warnings)

    # InterestPayments (required)
    ipmts = _sub(ip_elem, "InterestPayments")

    freq = f.get("interest_payment_frequency")
    _req(ipmts, "InterestPaymentFrequency", freq, warnings)

    # PayableDate (required, 1..4): derive from maturity date + frequency
    maturity = f.get("maturity_date")
    payable_dates = _derive_payable_dates(maturity, freq)
    if payable_dates:
        for day, month in payable_dates:
            pd_elem = _sub(ipmts, "PayableDate")
            _sub(pd_elem, "Day", str(day))
            _sub(pd_elem, "Month", str(month))
    else:
        warnings.append(
            "Cannot derive PayableDate — maturity_date or interest_payment_frequency missing"
        )  # noqa: E501

    # FirstPayment (required): use first_interest_payment_date if available
    first_payment_date = f.get("first_interest_payment_date")
    if first_payment_date:
        fp_elem = _sub(ipmts, "FirstPayment")
        _sub(fp_elem, "PaymentDate", first_payment_date)
    else:
        warnings.append(
            "first_interest_payment_date missing — FirstPayment element omitted (XSD requires it)"
        )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _sub(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    """Create a child element in the BDT namespace, optionally with text content."""
    elem = etree.SubElement(parent, f"{_N}{tag}")
    if text is not None:
        elem.text = str(text)
    return elem


def _req(
    parent: etree._Element,
    tag: str,
    value: str | None,
    warnings: list[str],
) -> etree._Element | None:
    """
    Add a required element.  If value is None, logs a warning and skips the
    element (which will trigger XSD validation failure → done_partial).
    """
    if value is None or str(value).strip() == "":
        warnings.append(f"Required field '{tag}' is missing")
        return None
    return _sub(parent, tag, str(value))


def _fmt_decimal(value: float | int | None) -> str | None:
    """Format a numeric value for XML decimal type."""
    if value is None:
        return None
    # Avoid unnecessary trailing zeros: 150000000.0 → "150000000"
    f = float(value)
    if f == int(f):
        return str(int(f))
    return str(f)


def _fmt_rate(rate: float) -> str:
    """
    Convert interest rate to BDT representation (percentage, not decimal fraction).

    Stage 5c stores rates as decimal fractions (0.055 = 5.5%).
    BDT XML stores rates as percentages (5.5 = 5.5%).
    Rule: if 0 < rate < 1, multiply by 100.
    """
    if 0 < rate < 1:
        pct = round(rate * 100, 6)
        # Remove trailing zeros
        formatted = f"{pct:.6f}".rstrip("0").rstrip(".")
        return formatted
    return _fmt_decimal(rate) or str(rate)


def _derive_payable_dates(
    maturity_date: str | None,
    frequency: str | None,
) -> list[tuple[int, int]]:
    """
    Derive recurring interest payment (day, month) pairs from maturity date.

    Returns list of (day, month) tuples sorted by month.
    Empty list if inputs are insufficient.
    """
    if not maturity_date:
        return []
    try:
        d = date.fromisoformat(maturity_date)
    except (ValueError, TypeError):
        return []

    day = d.day
    month = d.month

    if frequency == "SEMIANNUALLY":
        month2 = ((month - 1 + 6) % 12) + 1
        return sorted([(day, month), (day, month2)], key=lambda x: x[1])
    if frequency == "QUARTERLY":
        months = sorted(set(((month - 1 + i * 3) % 12) + 1 for i in range(4)))
        return [(day, m) for m in months]
    # ANNUALLY, NONE, ZERO_COUPON, or unknown → single date at maturity
    return [(day, month)]


# ---------------------------------------------------------------------------
# XSD validation
# ---------------------------------------------------------------------------


def _validate_xsd(
    root: etree._Element,
    xsd_dir: Path,
) -> tuple[bool, list[str]]:
    """
    Validate an XML element tree against the ICMA BDT v1.2 XSD.

    Returns (is_valid, list_of_error_messages).
    """
    xsd_path = xsd_dir / "icma-bond-data-taxonomy.xsd"
    try:
        schema_doc = etree.parse(str(xsd_path))
        schema = etree.XMLSchema(schema_doc)
        schema.validate(root)
        errors = [str(e) for e in schema.error_log]
        return len(errors) == 0, errors
    except etree.XMLSchemaParseError as exc:
        return False, [f"Schema parse error: {exc}"]
    except OSError as exc:
        return False, [f"Cannot load XSD: {exc}"]
