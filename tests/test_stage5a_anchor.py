"""Tests for Stage 5a — Bond Anchor Extraction (ISIN regex + checksum)."""

from __future__ import annotations

import pytest

from pipeline.stage4_table import TableDetectionResult
from pipeline.stage5a_anchor import _isin_checksum_valid, extract_anchor
from tests.conftest import PDF_PATHS, requires_pdf

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


# ---------------------------------------------------------------------------
# Unit tests for full-document fallback
# ---------------------------------------------------------------------------


class TestAnchorFallback:
    """Verify that ISINs in full_doc_fallback_text are found as last resort."""

    def _make_table_result(
        self,
        table_text: str = "",
        section_text: str = "",
        fallback_text: str | None = None,
    ) -> TableDetectionResult:
        return TableDetectionResult(
            section_title="DESCRIPTION OF THE NOTES",
            table_text=table_text,
            full_section_text=section_text,
            table_found=bool(table_text),
            table_char_count=len(table_text),
            section_char_count=len(section_text),
            full_doc_fallback_text=fallback_text,
        )

    def test_fallback_finds_isin_when_section_empty(self):
        """ISIN only in full_doc_fallback_text — must be found."""
        cover_text = "This offering. ISIN: USP3710FAU86. Dated 2020."
        result = self._make_table_result(fallback_text=cover_text)
        anchor = extract_anchor(result)
        assert "USP3710FAU86" in anchor.isins

    def test_section_isin_takes_precedence(self):
        """ISINs from section appear before fallback ISINs in the list."""
        result = self._make_table_result(
            table_text="ISIN: USG38327AB13",
            fallback_text="Cover ISIN: USP3710FAU86",
        )
        anchor = extract_anchor(result)
        assert "USG38327AB13" in anchor.isins
        assert anchor.isins[0] == "USG38327AB13", "Section ISIN should come first"

    def test_no_fallback_no_isins(self):
        """When fallback is None and section has no ISINs, isins list is empty."""
        result = self._make_table_result(
            table_text="Maturity Date: 2030. Interest Rate: 5.00%.",
            fallback_text=None,
        )
        anchor = extract_anchor(result)
        assert anchor.isins == []

    def test_invalid_isin_in_fallback_excluded(self):
        """Regex-matching but checksum-failing strings in fallback are excluded."""
        result = self._make_table_result(fallback_text="See ISIN US0378331006 for details.")
        anchor = extract_anchor(result)
        assert "US0378331006" not in anchor.isins
        assert "US0378331006" in anchor.raw_isin_candidates  # captured but filtered


# ---------------------------------------------------------------------------
# Integration tests: fixtures whose ISINs live in document front-matter
# ---------------------------------------------------------------------------

# Module-level cache to avoid re-parsing PDFs per test
_pdf_doc_cache: dict[str, object] = {}
_pdf_sections_cache: dict[str, list] = {}
_pdf_tables_cache: dict[str, list] = {}


def _build_table_result(name: str, section_idx: int = 0) -> TableDetectionResult:
    """Build a TableDetectionResult for a fixture, passing the parsed doc for fallback."""
    if name not in _pdf_doc_cache:
        from pipeline.stage2_parse import parse_pdf
        from pipeline.stage3_find import find_bond_sections
        from pipeline.stage4_table import detect_summary_table

        doc = parse_pdf(PDF_PATHS[name])
        sections = find_bond_sections(doc)
        _pdf_doc_cache[name] = doc
        _pdf_sections_cache[name] = sections
        _pdf_tables_cache[name] = [detect_summary_table(s, parsed_doc=doc) for s in sections]

    tables = _pdf_tables_cache[name]
    if section_idx >= len(tables):
        pytest.skip(f"{name}: no section at index {section_idx}")
    return tables[section_idx]


class TestAnchorWithFallback:
    """
    Integration tests verifying that ISINs are found via full-document fallback
    for fixtures where the ISIN lives on the cover page or in front-matter.
    """

    @requires_pdf
    def test_edenor_finds_isins(self):
        """EDENOR: dual ISINs (144A + Reg S) expected via document fallback."""
        table = _build_table_result("edenor")
        anchor = extract_anchor(table)
        assert len(anchor.isins) >= 1, f"EDENOR: expected ISINs, got {anchor.isins}"
        for isin in anchor.isins:
            assert _isin_checksum_valid(isin)

    @requires_pdf
    def test_csn_finds_isins(self):
        """CSN: at least one ISIN expected via document fallback."""
        table = _build_table_result("csn")
        anchor = extract_anchor(table)
        assert len(anchor.isins) >= 1, f"CSN: expected ISINs, got {anchor.isins}"
        for isin in anchor.isins:
            assert _isin_checksum_valid(isin)

    @requires_pdf
    def test_liquid_telecom_finds_isins(self):
        """Liquid Telecom: ISIN XS2278474924 expected via document fallback."""
        table = _build_table_result("liquid_telecom")
        anchor = extract_anchor(table)
        assert len(anchor.isins) >= 1, f"Liquid Telecom: expected ISINs, got {anchor.isins}"
        for isin in anchor.isins:
            assert _isin_checksum_valid(isin)
