"""Tests for Stage 5c — Deterministic Post-processing.

All tests are pure unit tests — no PDF fixtures, no LLM, no network.
"""

from __future__ import annotations

import pytest

from pipeline.stage5a_anchor import BondAnchor
from pipeline.stage5b_llm import GroupExtractionResult, RawExtractionResult
from pipeline.stage5c_post import (
    ExtractionResult,
    ValidationWarning,
    derive_target_market,
    normalize_amount,
    normalize_date,
    post_process,
    validate_enum,
    validate_isin,
)
from bdt.enums import GOVERNING_LAW, INTEREST_TYPE


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------


class TestNormalizeDate:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            pytest.param("January 9, 2030", "2030-01-09", id="us_format"),
            pytest.param("2030-01-09", "2030-01-09", id="iso_already"),
            pytest.param("9 January 2030", "2030-01-09", id="european"),
            pytest.param("01/09/2030", "2030-01-09", id="us_slash"),
            pytest.param("September 21, 2027", "2027-09-21", id="sept_2027"),
        ],
    )
    def test_valid_dates(self, input_val, expected):
        result, warning = normalize_date(input_val, "test_field")
        assert result == expected
        assert warning is None

    def test_none_input(self):
        result, warning = normalize_date(None, "test_field")
        assert result is None
        assert warning is None

    def test_empty_string(self):
        result, warning = normalize_date("", "test_field")
        assert result is None
        assert warning is None

    def test_unparseable(self):
        result, warning = normalize_date("not a date at all xyz", "test_field")
        assert result is None
        assert warning is not None
        assert "Cannot parse" in warning.message


# ---------------------------------------------------------------------------
# Amount normalization
# ---------------------------------------------------------------------------


class TestNormalizeAmount:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            pytest.param("500000000", 500000000.0, id="plain"),
            pytest.param("500,000,000", 500000000.0, id="commas"),
            pytest.param("US$500,000,000", 500000000.0, id="us_dollar"),
            pytest.param("$500,000,000", 500000000.0, id="dollar_sign"),
            pytest.param("€200,000", 200000.0, id="euro"),
            pytest.param(500000000, 500000000.0, id="already_numeric"),
            pytest.param("100.0", 100.0, id="decimal"),
            pytest.param("98.5", 98.5, id="issue_price"),
        ],
    )
    def test_valid_amounts(self, input_val, expected):
        result, warning = normalize_amount(input_val, "test_field")
        assert result == expected
        assert warning is None

    def test_percentage(self):
        result, warning = normalize_amount("5.5%", "interest_rate")
        assert result == pytest.approx(0.055)
        assert warning is None

    def test_none_input(self):
        result, warning = normalize_amount(None, "test_field")
        assert result is None
        assert warning is None

    def test_unparseable(self):
        result, warning = normalize_amount("not a number", "test_field")
        assert result is None
        assert warning is not None


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


class TestValidateEnum:
    def test_exact_match(self):
        result, warning = validate_enum("FIXED", "interest_type", INTEREST_TYPE)
        assert result == "FIXED"
        assert warning is None

    def test_case_insensitive(self):
        result, warning = validate_enum("fixed", "interest_type", INTEREST_TYPE)
        assert result == "FIXED"
        assert warning is None

    def test_hyphen_normalization(self):
        result, warning = validate_enum("NEW-YORK-LAW", "governing_law", GOVERNING_LAW)
        assert result == "NEW_YORK_LAW"
        assert warning is None

    def test_invalid_value(self):
        result, warning = validate_enum("NONSENSE", "interest_type", INTEREST_TYPE)
        assert result is None
        assert warning is not None
        assert "not in allowed list" in warning.message

    def test_none_passthrough(self):
        result, warning = validate_enum(None, "interest_type", INTEREST_TYPE)
        assert result is None
        assert warning is None


# ---------------------------------------------------------------------------
# ISIN validation
# ---------------------------------------------------------------------------


class TestValidateISIN:
    def test_valid(self):
        assert validate_isin("US0378331005")

    def test_invalid(self):
        assert not validate_isin("US0378331006")


# ---------------------------------------------------------------------------
# Target market derivation
# ---------------------------------------------------------------------------


class TestDeriveTargetMarket:
    def test_144a_only(self):
        result = derive_target_market(["144A", "REGS_CAT2"])
        assert result == ["NOT_APPLICABLE"]

    def test_empty(self):
        result = derive_target_market([])
        assert result == ["NOT_APPLICABLE"]

    def test_none(self):
        result = derive_target_market(None)
        assert result == ["NOT_APPLICABLE"]


# ---------------------------------------------------------------------------
# Full post-processing pipeline
# ---------------------------------------------------------------------------


class TestPostProcess:
    def _make_raw_result(self, group_fields: dict[str, dict]) -> RawExtractionResult:
        """Helper to build a RawExtractionResult from group field dicts."""
        anchor = BondAnchor(
            bond_name="Test Bond",
            isins=["US0378331005"],
            raw_isin_candidates=["US0378331005"],
        )
        groups = {}
        for group_name, fields in group_fields.items():
            groups[group_name] = GroupExtractionResult(
                group_name=group_name,
                fields=fields,
            )
        return RawExtractionResult(anchor=anchor, groups=groups)

    def test_full_valid_result(self):
        raw = self._make_raw_result({
            "identifiers": {"isin": "US0378331005"},
            "amounts": {
                "aggregate_nominal_amount": "500,000,000",
                "specified_denomination": "200000",
                "specified_currency": "USD",
            },
            "dates": {
                "pricing_date": "January 15, 2020",
                "issue_date": "January 17, 2020",
                "settlement_date": "January 17, 2020",
                "maturity_date": "September 21, 2027",
                "interest_commencement_date": "January 17, 2020",
            },
            "interest": {
                "interest_type": "FIXED",
                "interest_rate": "0.055",
                "interest_payment_frequency": "SEMIANNUALLY",
                "day_count_fraction": "30/360",
                "business_day_convention": "FOLLOWING_UNADJUSTED",
                "business_day_center": "NEW_YORK",
            },
            "issuance": {
                "issuance_type": "STANDALONE",
                "issue_price": "100.0",
                "form_of_note": "REGISTERED",
                "status_of_note": "SENIOR_UNSECURED",
                "governing_law": "NEW_YORK_LAW",
            },
            "restrictions": {
                "selling_restrictions": ["144A", "REGS_CAT2"],
            },
        })
        result = post_process(raw)
        assert result.status == "done_valid"
        assert result.fields["maturity_date"] == "2027-09-21"
        assert result.fields["aggregate_nominal_amount"] == 500000000.0
        assert result.fields["interest_type"] == "FIXED"

    def test_missing_required_fields_partial(self):
        raw = self._make_raw_result({
            "identifiers": {"isin": "US0378331005"},
            "amounts": {"specified_currency": "USD"},
        })
        result = post_process(raw)
        assert result.status == "done_partial"
        assert any(w.field_name == "__required__" for w in result.warnings)

    def test_invalid_enum_produces_warning(self):
        raw = self._make_raw_result({
            "interest": {"interest_type": "NONSENSE_VALUE"},
        })
        result = post_process(raw)
        assert result.fields["interest_type"] is None
        assert any(
            w.field_name == "interest_type" and "not in allowed list" in w.message
            for w in result.warnings
        )

    def test_date_normalization_in_pipeline(self):
        raw = self._make_raw_result({
            "dates": {"maturity_date": "September 21, 2027"},
        })
        result = post_process(raw)
        assert result.fields["maturity_date"] == "2027-09-21"

    def test_parties_extracted(self):
        raw = self._make_raw_result({
            "parties": {
                "issuer_name": "GeoPark Limited",
                "lead_managers": ["J.P. Morgan", "Morgan Stanley"],
                "trustee": "The Bank of New York Mellon",
            },
        })
        result = post_process(raw)
        assert len(result.parties) == 4  # issuer + 2 managers + trustee
        roles = [p.role for p in result.parties]
        assert "ISSUER" in roles
        assert "TRUSTEE" in roles

    def test_target_market_derived(self):
        raw = self._make_raw_result({
            "restrictions": {"selling_restrictions": ["144A", "REGS_CAT2"]},
        })
        result = post_process(raw)
        assert result.manufacturer_target_market == ["NOT_APPLICABLE"]
