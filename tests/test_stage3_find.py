"""Tests for Stage 3 — Section Finding (heading detection)."""

from __future__ import annotations

import pytest

from pipeline.stage3_find import _is_target_heading
from tests.conftest import requires_pdf


class TestFindGeoPark:
    """Integration tests using the GeoPark fixture."""

    @requires_pdf
    def test_finds_at_least_one_section(self, geopark_sections):
        assert len(geopark_sections) >= 1, "GeoPark should have at least one bond section"

    @requires_pdf
    def test_section_title_matches_target(self, geopark_sections):
        titles_lower = [s.title.lower() for s in geopark_sections]
        assert any(
            "description" in t or "terms" in t for t in titles_lower
        ), f"No section title contains 'description' or 'terms': {titles_lower}"

    @requires_pdf
    def test_section_text_not_empty(self, geopark_sections):
        for section in geopark_sections:
            assert len(section.text.strip()) > 0, f"Section '{section.title}' has empty text"

    @requires_pdf
    def test_section_text_contains_bond_keywords(self, geopark_sections):
        keywords = {"maturity", "interest", "isin"}
        for section in geopark_sections:
            text_lower = section.text.lower()
            found = {kw for kw in keywords if kw in text_lower}
            assert len(found) >= 1, (
                f"Section '{section.title}' missing bond keywords. "
                f"Expected at least one of {keywords}"
            )

    @requires_pdf
    def test_match_score_above_threshold(self, geopark_sections):
        for section in geopark_sections:
            assert section.match_score >= 85, (
                f"Section '{section.title}' has score {section.match_score} < 85"
            )

    @requires_pdf
    def test_page_range_valid(self, geopark_sections):
        for section in geopark_sections:
            assert 1 <= section.page_start <= 191
            assert 1 <= section.page_end <= 191
            assert section.page_start <= section.page_end


class TestIsTargetHeading:
    """Unit tests for the heading matcher (no PDF needed)."""

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("Description of the Notes", id="exact"),
            pytest.param("DESCRIPTION OF THE NOTES", id="all_caps"),
            pytest.param("Description of the Bonds", id="bonds_variant"),
            pytest.param("Terms and Conditions of the Notes", id="terms_notes"),
            pytest.param("Terms and Conditions", id="terms_short"),
            pytest.param("TERMS AND CONDITIONS OF THE BONDS", id="terms_bonds_caps"),
            pytest.param("Description of the Securities", id="securities"),
            pytest.param("DESCRIPTION OF THE NEW SECURITIES", id="new_securities_caps"),
        ],
    )
    def test_positive_matches(self, text):
        matched, score, target = _is_target_heading(text)
        assert matched, f"Expected match for '{text}', got score {score}"
        assert score >= 85

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("Random paragraph about nothing", id="random"),
            pytest.param("", id="empty"),
            pytest.param("abc", id="too_short"),
            pytest.param("A" * 100, id="too_long"),
            pytest.param("Use of Proceeds", id="terminator_heading"),
            pytest.param("Risk Factors", id="risk_factors"),
            pytest.param(
                "For a description of the Notes and the terms of the indenture, see the discussion under Description of the Notes",
                id="cross_reference_long",
            ),
        ],
    )
    def test_negative_matches(self, text):
        matched, score, _ = _is_target_heading(text)
        assert not matched, f"Unexpected match for '{text}', score {score}"
