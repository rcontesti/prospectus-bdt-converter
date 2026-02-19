"""
Tests for Stage 6 — XML Assembly and XSD Validation.

Unit tests use a synthetic ExtractionResult built from known GeoPark bond data
so no PDF fixtures or Ollama connection are needed.

Integration tests (requires_pdf + requires_ollama) run the full pipeline
and verify that the assembled XML passes XSD validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from pipeline.stage5c_post import ExtractionResult, PartyInfo, ValidationWarning
from pipeline.stage6_assemble import (
    BDT_NS,
    AssemblyResult,
    _derive_payable_dates,
    _fmt_rate,
    assemble,
)

# ---------------------------------------------------------------------------
# Synthetic fixture: GeoPark bond with all required fields and a fake valid LEI
# ---------------------------------------------------------------------------

_FAKE_LEI = "AAAAAAAAAAAAAAAAAA00"  # 18 alphanumeric + 00 — matches XSD pattern

_GEOPARK_FIELDS: dict = {
    # Identifiers
    "isin": "USG38327AB13",
    "cusip": "G38327AB1",  # alphanumeric — will be skipped with warning
    "common_code": "233279448",  # 9 chars — valid
    # Amounts
    "aggregate_nominal_amount": 150_000_000.0,
    "specified_denomination": 200_000.0,
    "integral_multiples": 1_000.0,
    "issue_price": 100.0,
    "interest_rate": 0.055,
    # Dates
    "pricing_date": "2021-07-13",
    "issue_date": "2021-07-16",
    "settlement_date": "2021-07-16",
    "maturity_date": "2027-01-17",
    "interest_commencement_date": "2021-07-17",
    "first_interest_payment_date": "2022-01-17",
    # Interest terms
    "interest_type": "FIXED",
    "interest_payment_frequency": "SEMIANNUALLY",
    "day_count_fraction": "30/360",
    "business_day_convention": "FOLLOWING_UNADJUSTED",
    "business_day_center": "NEW_YORK",
    # Issuance
    "issuance_type": "STANDALONE",
    "form_of_note": "REGISTERED",
    "status_of_note": "SENIOR_UNSECURED",
    "specified_currency": "USD",
    "governing_law": "NEW_YORK_LAW",
    "selling_restrictions": ["144A", "REGS_CAT2"],
}

_GEOPARK_PARTIES = [
    PartyInfo(name="GeoPark Limited", role="ISSUER", lei=_FAKE_LEI, lei_resolved=True),
    PartyInfo(name="Citibank N.A.", role="TRUSTEE", lei=_FAKE_LEI, lei_resolved=True),
]


def _make_result(
    fields: dict | None = None,
    parties: list[PartyInfo] | None = None,
    status: str = "done_valid",
    warnings: list[ValidationWarning] | None = None,
) -> ExtractionResult:
    return ExtractionResult(
        anchor_bond_name="GeoPark Limited 5.500% Senior Notes due 2027",
        anchor_isins=["USG38327AB13"],
        fields=fields if fields is not None else dict(_GEOPARK_FIELDS),
        parties=parties if parties is not None else list(_GEOPARK_PARTIES),
        warnings=warnings or [],
        status=status,
        manufacturer_target_market=["NOT_APPLICABLE"],
    )


# ---------------------------------------------------------------------------
# Unit tests: interest rate formatting
# ---------------------------------------------------------------------------


class TestFmtRate:
    def test_decimal_fraction_converted_to_percentage(self):
        assert _fmt_rate(0.055) == "5.5"

    def test_small_rate_converted(self):
        assert _fmt_rate(0.0875) == "8.75"

    def test_already_percentage_unchanged(self):
        # 5.5 >= 1 → kept as-is
        assert _fmt_rate(5.5) == "5.5"

    def test_one_percent(self):
        assert _fmt_rate(0.01) == "1"

    def test_zero_rate(self):
        # 0 is not in (0,1) so treated as-is
        assert _fmt_rate(0.0) == "0"


# ---------------------------------------------------------------------------
# Unit tests: payable date derivation
# ---------------------------------------------------------------------------


class TestDerivePayableDates:
    def test_semiannual_jan_maturity(self):
        dates = _derive_payable_dates("2027-01-17", "SEMIANNUALLY")
        assert len(dates) == 2
        assert (17, 1) in dates  # January
        assert (17, 7) in dates  # July (6 months later)

    def test_semiannual_jul_maturity(self):
        dates = _derive_payable_dates("2027-07-15", "SEMIANNUALLY")
        assert len(dates) == 2
        assert (15, 1) in dates
        assert (15, 7) in dates

    def test_annual_maturity(self):
        dates = _derive_payable_dates("2030-11-30", "ANNUALLY")
        assert dates == [(30, 11)]

    def test_quarterly_maturity(self):
        dates = _derive_payable_dates("2030-03-15", "QUARTERLY")
        assert len(dates) == 4
        months = {m for _, m in dates}
        assert months == {3, 6, 9, 12}

    def test_missing_maturity_returns_empty(self):
        assert _derive_payable_dates(None, "SEMIANNUALLY") == []

    def test_missing_frequency_falls_back_to_single(self):
        dates = _derive_payable_dates("2027-01-17", None)
        assert dates == [(17, 1)]


# ---------------------------------------------------------------------------
# Unit tests: XML assembly structure
# ---------------------------------------------------------------------------


class TestAssembleStructure:
    def test_returns_assembly_result(self):
        result = assemble(_make_result())
        assert isinstance(result, AssemblyResult)

    def test_xml_bytes_non_empty(self):
        result = assemble(_make_result())
        assert len(result.xml_bytes) > 0

    def test_xml_declaration_present(self):
        result = assemble(_make_result())
        assert result.xml_bytes.startswith(b"<?xml")

    def test_filename_uses_primary_isin(self):
        result = assemble(_make_result())
        assert result.filename == "USG38327AB13.xml"

    def test_bdt_namespace_in_root(self):
        result = assemble(_make_result())
        root = etree.fromstring(result.xml_bytes)
        assert root.nsmap.get(None) == BDT_NS

    def test_root_element_is_document(self):
        result = assemble(_make_result())
        root = etree.fromstring(result.xml_bytes)
        assert root.tag == f"{{{BDT_NS}}}Document"

    def test_party_role_present(self):
        result = assemble(_make_result())
        root = etree.fromstring(result.xml_bytes)
        roles = root.findall(f".//{{{BDT_NS}}}PartyRoleType")
        role_texts = [r.text for r in roles]
        assert "ISSUER" in role_texts

    def test_isin_in_output(self):
        result = assemble(_make_result())
        assert b"USG38327AB13" in result.xml_bytes

    def test_interest_rate_as_percentage(self):
        result = assemble(_make_result())
        # 0.055 should appear as 5.5 not 0.055
        assert b"5.5" in result.xml_bytes
        assert b"0.055" not in result.xml_bytes

    def test_aggregate_nominal_amount(self):
        result = assemble(_make_result())
        assert b"150000000" in result.xml_bytes

    def test_maturity_date(self):
        result = assemble(_make_result())
        assert b"2027-01-17" in result.xml_bytes

    def test_semiannual_payable_dates(self):
        result = assemble(_make_result())
        root = etree.fromstring(result.xml_bytes)
        payable_dates = root.findall(f".//{{{BDT_NS}}}PayableDate")
        assert len(payable_dates) == 2

    def test_common_code_included(self):
        result = assemble(_make_result())
        assert b"233279448" in result.xml_bytes

    def test_cusip_skipped_with_warning(self):
        # GeoPark CUSIP is alphanumeric (G38327AB1) — BDT only accepts 9 digits
        result = assemble(_make_result())
        root = etree.fromstring(result.xml_bytes)
        # No <CUSIP> element should exist
        cusip_elems = root.findall(f".//{{{BDT_NS}}}CUSIP")
        assert len(cusip_elems) == 0
        assert any("CUSIP" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Unit tests: XSD validation (requires bundled .docs XSD)
# ---------------------------------------------------------------------------


_XSD_DIR = Path(__file__).parent.parent / ".docs" / "ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02"


@pytest.mark.skipif(not _XSD_DIR.exists(), reason="XSD files not present")
class TestXSDValidation:
    def test_complete_bond_passes_xsd(self):
        """A complete GeoPark bond with valid LEI should pass XSD validation."""
        result = assemble(_make_result())
        assert result.xsd_valid, "Expected XSD-valid document but got errors:\n" + "\n".join(
            result.xsd_errors
        )

    def test_complete_bond_status_done_valid(self):
        result = assemble(_make_result())
        assert result.status == "done_valid"

    def test_missing_required_field_fails_xsd(self):
        fields = dict(_GEOPARK_FIELDS)
        del fields["maturity_date"]
        result = assemble(_make_result(fields=fields, status="done_partial"))
        assert not result.xsd_valid
        assert result.status == "done_partial"

    def test_xsd_errors_listed(self):
        fields = dict(_GEOPARK_FIELDS)
        del fields["governing_law"]
        del fields["form_of_note"]
        result = assemble(_make_result(fields=fields, status="done_partial"))
        assert len(result.xsd_errors) > 0

    def test_no_lei_fails_xsd(self):
        """Parties without valid LEI should cause XSD failure (PLACEHOLDER)."""
        parties = [PartyInfo(name="Unknown Corp", role="ISSUER")]  # no LEI
        result = assemble(_make_result(parties=parties))
        assert not result.xsd_valid

    def test_same_party_deduplicated(self):
        """Same party in multiple roles → one <Party> element, two <PartyRole> elements."""
        lei = _FAKE_LEI
        parties = [
            PartyInfo(name="GeoPark Limited", role="ISSUER", lei=lei, lei_resolved=True),
            PartyInfo(name="GeoPark Limited", role="GUARANTOR", lei=lei, lei_resolved=True),
        ]
        result = assemble(_make_result(parties=parties))
        root = etree.fromstring(result.xml_bytes)
        party_elems = root.findall(f".//{{{BDT_NS}}}Party")
        assert len(party_elems) == 1, "Duplicate party should be deduplicated"
        role_elems = root.findall(f".//{{{BDT_NS}}}PartyRole")
        assert len(role_elems) == 2, "Both roles should be emitted"


# ---------------------------------------------------------------------------
# Unit tests: done_partial handling
# ---------------------------------------------------------------------------


class TestDonePartial:
    def test_partial_status_adds_warnings_comment(self):
        fields = dict(_GEOPARK_FIELDS)
        del fields["maturity_date"]
        result = assemble(_make_result(fields=fields, status="done_partial"))
        assert b"ValidationWarnings" in result.xml_bytes

    def test_partial_xml_still_parseable(self):
        """Even a partial bond should produce parseable XML."""
        # Provide almost no fields — just the bare minimum
        minimal = {
            "issuance_type": "STANDALONE",
            "specified_denomination": 1000.0,
            "specified_currency": "USD",
            "pricing_date": "2024-01-01",
            "issue_date": "2024-01-01",
            "settlement_date": "2024-01-01",
            "issue_price": 100.0,
            "governing_law": "NEW_YORK_LAW",
            "selling_restrictions": ["NOT_APPLICABLE"],
            "form_of_note": "REGISTERED",
            "status_of_note": "SENIOR_UNSECURED",
            "aggregate_nominal_amount": 1_000_000.0,
            "interest_type": "FIXED",
            "interest_commencement_date": "2024-01-01",
            "interest_payment_frequency": "ANNUALLY",
            "day_count_fraction": "30/360",
            "business_day_convention": "FOLLOWING_UNADJUSTED",
            "business_day_center": "NEW_YORK",
        }
        result = assemble(
            ExtractionResult(
                anchor_bond_name="Test Bond",
                anchor_isins=["US0231351067"],
                fields=minimal,
                parties=[PartyInfo(name="Test Corp", role="ISSUER")],
                status="done_partial",
                manufacturer_target_market=["NOT_APPLICABLE"],
            )
        )
        # Should parse without raising
        root = etree.fromstring(result.xml_bytes.split(b"<!--")[0])
        assert root is not None

    def test_no_parties_adds_placeholder(self):
        result = assemble(
            ExtractionResult(
                anchor_bond_name="Test",
                anchor_isins=["US0231351067"],
                fields=dict(_GEOPARK_FIELDS),
                parties=[],
                status="done_partial",
                manufacturer_target_market=["NOT_APPLICABLE"],
            )
        )
        assert b"UNKNOWN" in result.xml_bytes
        assert any("No parties" in w for w in result.warnings)
