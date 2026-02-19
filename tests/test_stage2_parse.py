"""Tests for Stage 2 — PDF Parsing."""

from __future__ import annotations

import pytest

from tests.conftest import requires_pdf


class TestParseGeoPark:
    """Integration tests using the GeoPark fixture (simplest single bond)."""

    @requires_pdf
    def test_page_count(self, geopark_doc):
        assert geopark_doc.page_count == 191

    @requires_pdf
    def test_pages_have_text(self, geopark_doc):
        empty_pages = [p for p in geopark_doc.pages if not p.raw_text.strip()]
        assert len(empty_pages) == 0, f"{len(empty_pages)} pages have no text"

    @requires_pdf
    def test_block_types_present(self, geopark_doc):
        all_types = {b.type for p in geopark_doc.pages for b in p.blocks}
        assert "heading" in all_types, "No heading blocks detected"
        assert "paragraph" in all_types, "No paragraph blocks detected"
        assert "table_row" in all_types, "No table_row blocks detected"

    @requires_pdf
    def test_is_not_scanned(self, geopark_doc):
        assert geopark_doc.is_scanned is False

    @requires_pdf
    def test_full_text_formfeeds(self, geopark_doc):
        text = geopark_doc.full_text
        formfeeds = text.count("\f")
        assert formfeeds == 190, f"Expected 190 form-feeds (191 pages), got {formfeeds}"

    @requires_pdf
    def test_page_numbering_one_indexed(self, geopark_doc):
        assert geopark_doc.pages[0].page_number == 1
        assert geopark_doc.pages[-1].page_number == 191


class TestParsePdfErrors:
    """Unit tests for error handling (no PDF fixture needed)."""

    def test_missing_file_raises(self):
        from pipeline.stage2_parse import parse_pdf

        with pytest.raises(FileNotFoundError, match="PDF not found"):
            parse_pdf("/nonexistent/path/to/file.pdf")
