"""Tests for Stage 5a — Bond Anchor Extraction (ISIN regex + checksum)."""

from __future__ import annotations

import pytest

from pipeline.stage5a_anchor import BondAnchor, _isin_checksum_valid, extract_anchor
from tests.conftest import requires_pdf


# ---------------------------------------------------------------------------
# ISIN checksum unit tests
# ---------------------------------------------------------------------------


class TestISINChecksum:
    """Pure unit tests for ISO 6166 Luhn check digit validation."""

    @pytest.mark.parametrize(
        "isin",
        [
            pytest.param("US0378331005", id="apple"),
            pytest.param("GB0002634946", id="bae_systems"),
            pytest.param("XS2385150334", id="xs_bond"),
            pytest.param("USG38327AB13", id="geopark_cusip_isin"),
            pytest.param("USP3710FAU86", id="edenor"),
            pytest.param("US29244AAM45", id="edenor_144a"),
            pytest.param("USL21779AD28", id="csn"),
            pytest.param("XS2278474924", id="liquid_telecom"),
        ],
    )
    def test_valid_isins(self, isin):
        assert _isin_checksum_valid(isin), f"ISIN '{isin}' should be valid"

    @pytest.mark.parametrize(
        "isin",
        [
            pytest.param("US0378331006", id="wrong_check_digit"),
            pytest.param("INVALIDISINH", id="not_an_isin"),
            pytest.param("SHORT", id="too_short"),
            pytest.param("US037833100500", id="too_long"),
            pytest.param("", id="empty"),
            pytest.param("123456789012", id="all_digits_invalid"),
        ],
    )
    def test_invalid_isins(self, isin):
        assert not _isin_checksum_valid(isin), f"ISIN '{isin}' should be invalid"

    def test_length_check(self):
        assert not _isin_checksum_valid("US03783")
        assert not _isin_checksum_valid("US037833100500000")


# ---------------------------------------------------------------------------
# Integration tests with GeoPark
# ---------------------------------------------------------------------------


class TestAnchorGeoPark:
    """Integration tests: extract anchor from real GeoPark table result."""

    @requires_pdf
    def test_extracts_isins(self, geopark_table):
        anchor = extract_anchor(geopark_table)
        assert len(anchor.isins) >= 1, "GeoPark should have at least one valid ISIN"

    @requires_pdf
    def test_isins_pass_checksum(self, geopark_table):
        anchor = extract_anchor(geopark_table)
        for isin in anchor.isins:
            assert _isin_checksum_valid(isin), f"Extracted ISIN '{isin}' fails checksum"

    @requires_pdf
    def test_bond_name_not_empty(self, geopark_table):
        anchor = extract_anchor(geopark_table)
        assert len(anchor.bond_name.strip()) > 0

    @requires_pdf
    def test_raw_candidates_superset(self, geopark_table):
        anchor = extract_anchor(geopark_table)
        assert len(anchor.raw_isin_candidates) >= len(anchor.isins)
        for isin in anchor.isins:
            assert isin in anchor.raw_isin_candidates
