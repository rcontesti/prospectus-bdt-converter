"""Tests for Stage 4 — Summary Table Detection."""

from __future__ import annotations

import pytest

from tests.conftest import requires_pdf


class TestTableGeoPark:
    """Integration tests using the GeoPark fixture."""

    @requires_pdf
    def test_returns_result(self, geopark_table):
        from pipeline.stage4_table import TableDetectionResult

        assert isinstance(geopark_table, TableDetectionResult)

    @requires_pdf
    def test_table_text_not_empty(self, geopark_table):
        assert len(geopark_table.table_text.strip()) > 0, "Table text should not be empty"

    @requires_pdf
    def test_table_is_subset_of_section(self, geopark_table):
        assert geopark_table.table_char_count < geopark_table.section_char_count, (
            "Table should be smaller than full section"
        )

    @requires_pdf
    def test_section_title_not_empty(self, geopark_table):
        assert len(geopark_table.section_title.strip()) > 0

    @requires_pdf
    def test_full_section_text_matches(self, geopark_sections, geopark_table):
        assert geopark_table.full_section_text == geopark_sections[0].text
