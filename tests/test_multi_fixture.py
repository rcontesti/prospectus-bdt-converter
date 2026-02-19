"""Parametrized cross-fixture tests for Stages 2-4.

Uses a module-level cache to avoid re-parsing PDFs per test method.
Each fixture is tested through the full Stage 2 → 3 → 4 pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FIXTURE_CATALOG, PDF_PATHS, requires_pdf

# Module-level cache: avoids re-parsing the same PDF for every test method.
_doc_cache: dict[str, object] = {}
_sections_cache: dict[str, list] = {}
_tables_cache: dict[str, list] = {}


def _get_doc(name: str):
    if name not in _doc_cache:
        from pipeline.stage2_parse import parse_pdf

        _doc_cache[name] = parse_pdf(PDF_PATHS[name])
    return _doc_cache[name]


def _get_sections(name: str):
    if name not in _sections_cache:
        from pipeline.stage3_find import find_bond_sections

        _sections_cache[name] = find_bond_sections(_get_doc(name))
    return _sections_cache[name]


def _get_tables(name: str):
    if name not in _tables_cache:
        from pipeline.stage4_table import detect_summary_table

        doc = _get_doc(name)
        sections = _get_sections(name)
        _tables_cache[name] = [detect_summary_table(s, parsed_doc=doc) for s in sections]
    return _tables_cache[name]


def _fixture_available(name: str) -> bool:
    return PDF_PATHS.get(name, Path("/missing")).exists()


# ---------------------------------------------------------------------------
# Parametrize helpers
# ---------------------------------------------------------------------------

_FIXTURES = [
    pytest.param("geopark", id="geopark"),
    pytest.param("edenor", id="edenor"),
    pytest.param("csn", id="csn"),
]


def _skip_if_missing(name: str) -> None:
    if not _fixture_available(name):
        pytest.skip(f"PDF fixture '{name}' not present in data/PDF/")


# ---------------------------------------------------------------------------
# Stage 2 — parse
# ---------------------------------------------------------------------------


class TestParseMulti:
    """Parametrized parse tests across all fixtures."""

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_page_count(self, name):
        _skip_if_missing(name)
        doc = _get_doc(name)
        expected = FIXTURE_CATALOG[name]["page_count"]
        assert doc.page_count == expected, (
            f"{name}: expected {expected} pages, got {doc.page_count}"
        )

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_not_scanned(self, name):
        _skip_if_missing(name)
        doc = _get_doc(name)
        assert doc.is_scanned is False, f"{name}: unexpectedly flagged as scanned"


# ---------------------------------------------------------------------------
# Stage 3 — find sections
# ---------------------------------------------------------------------------


class TestFindMulti:
    """Parametrized section-finding tests across all fixtures."""

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_min_sections(self, name):
        _skip_if_missing(name)
        sections = _get_sections(name)
        expected = FIXTURE_CATALOG[name]["min_sections"]
        assert len(sections) >= expected, (
            f"{name}: expected >= {expected} sections, got {len(sections)}"
        )

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_section_text_not_empty(self, name):
        _skip_if_missing(name)
        for section in _get_sections(name):
            assert len(section.text.strip()) > 0, (
                f"{name}: section '{section.title}' has empty text"
            )

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_match_score_valid(self, name):
        _skip_if_missing(name)
        for section in _get_sections(name):
            assert section.match_score >= 85, (
                f"{name}: section '{section.title}' score {section.match_score} < 85"
            )


# ---------------------------------------------------------------------------
# Stage 4 — table detection
# ---------------------------------------------------------------------------


class TestTableMulti:
    """Parametrized table detection tests across all fixtures."""

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_table_text_not_empty(self, name):
        _skip_if_missing(name)
        for table in _get_tables(name):
            assert len(table.table_text.strip()) > 0, (
                f"{name}: section '{table.section_title}' has empty table text"
            )

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_table_subset_of_section(self, name):
        _skip_if_missing(name)
        for table in _get_tables(name):
            assert table.table_char_count <= table.section_char_count, (
                f"{name}: table ({table.table_char_count}) larger than section "
                f"({table.section_char_count})"
            )
