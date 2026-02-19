"""
Write intermediate pipeline outputs to data/output/debug/ for manual inspection.

These tests run automatically with pytest and produce human-readable artefacts for
each fixture at every pipeline stage. No assertions beyond basic non-empty checks —
the files are the primary deliverable, meant to be read and diffed after changes.

Output location: data/output/debug/{fixture}_stage{N}_{description}.{ext}
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from pipeline.stage5c_post import ExtractionResult, PartyInfo
from tests.conftest import PDF_PATHS, requires_ollama, requires_pdf

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------

DEBUG_DIR = Path(__file__).parent.parent / "data" / "output" / "debug"

# ---------------------------------------------------------------------------
# Module-level pipeline cache (avoids re-parsing between test methods)
# ---------------------------------------------------------------------------

_doc_cache: dict[str, object] = {}
_sections_cache: dict[str, list] = {}
_tables_cache: dict[str, list] = {}
_anchors_cache: dict[str, list] = {}
_extraction_cache: dict[str, list] = {}
_assembly_cache: dict[str, list] = {}


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


def _get_anchors(name: str):
    if name not in _anchors_cache:
        from pipeline.stage5a_anchor import extract_anchor

        tables = _get_tables(name)
        _anchors_cache[name] = [extract_anchor(t) for t in tables]
    return _anchors_cache[name]


def _get_extraction(name: str):
    if name not in _extraction_cache:
        from pipeline.stage5_extract import extract_bond

        _extraction_cache[name] = [extract_bond(t) for t in _get_tables(name)]
    return _extraction_cache[name]


def _get_assembly(name: str):
    if name not in _assembly_cache:
        from pipeline.stage6_assemble import assemble

        _assembly_cache[name] = [assemble(e) for e in _get_extraction(name)]
    return _assembly_cache[name]


def _skip_if_missing(name: str) -> None:
    if not PDF_PATHS.get(name, Path("/missing")).exists():
        pytest.skip(f"PDF fixture '{name}' not present in data/PDF/")


def _out(filename: str) -> Path:
    """Return path to a debug output file, creating the directory if needed."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return DEBUG_DIR / filename


# ---------------------------------------------------------------------------
# Parametrize
# ---------------------------------------------------------------------------

_FIXTURES = [
    pytest.param("geopark", id="geopark"),
    pytest.param("edenor", id="edenor"),
    pytest.param("csn", id="csn"),
    pytest.param("pdvsa", id="pdvsa"),
    pytest.param("buenos_aires", id="buenos_aires"),
    pytest.param("argentina_424b5", id="argentina_424b5"),
    pytest.param("volcan", id="volcan"),
    pytest.param("liquid_telecom", id="liquid_telecom"),
    pytest.param("argentina_gdp", id="argentina_gdp"),
]


# ---------------------------------------------------------------------------
# Stage 2 — full extracted text
# ---------------------------------------------------------------------------


class TestWriteStage2:
    """Write full extracted text and parse statistics for each fixture."""

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_write_full_text(self, name: str) -> None:
        _skip_if_missing(name)
        doc = _get_doc(name)

        block_types: Counter[str] = Counter()
        for page in doc.pages:
            for block in page.blocks:
                block_types[block.type] += 1

        lines: list[str] = [
            f"=== Stage 2 Parse: {name.upper()} ===",
            f"Path:        {doc.path}",
            f"Page count:  {doc.page_count}",
            f"Is scanned:  {doc.is_scanned}",
            "",
            "Block type counts:",
            *(f"  {btype}: {count}" for btype, count in sorted(block_types.items())),
            "",
        ]

        for page in doc.pages:
            lines += [f"--- Page {page.page_number} ---", page.raw_text, ""]

        out = _out(f"{name}_stage2_full_text.txt")
        out.write_text("\n".join(lines), encoding="utf-8")
        assert out.stat().st_size > 0, f"Stage 2 output for {name} is empty"


# ---------------------------------------------------------------------------
# Stage 3 — sections found
# ---------------------------------------------------------------------------


class TestWriteStage3:
    """Write section-finding results: titles, scores, page ranges, and full text."""

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_write_sections(self, name: str) -> None:
        _skip_if_missing(name)
        sections = _get_sections(name)

        lines: list[str] = [
            f"=== Stage 3 Sections: {name.upper()} ===",
            f"Sections found: {len(sections)}",
            "",
        ]

        for i, section in enumerate(sections):
            lines += [
                "=" * 60,
                f"Section {i}: {section.title}",
                f"  match_score:    {section.match_score}",
                f"  target_matched: {section.target_matched}",
                f"  pages:          {section.page_start} \u2192 {section.page_end}",
                f"  text length:    {len(section.text):,} chars",
                "",
                section.text,
                "",
            ]

        out = _out(f"{name}_stage3_sections.txt")
        out.write_text("\n".join(lines), encoding="utf-8")
        assert out.stat().st_size > 0, f"Stage 3 output for {name} is empty"


# ---------------------------------------------------------------------------
# Stage 4 — table detection
# ---------------------------------------------------------------------------


class TestWriteStage4:
    """Write table detection results: table_found flag and extracted table_text."""

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_write_tables(self, name: str) -> None:
        _skip_if_missing(name)
        tables = _get_tables(name)

        lines: list[str] = [
            f"=== Stage 4 Tables: {name.upper()} ===",
            f"Sections: {len(tables)}",
            "",
        ]

        for i, table in enumerate(tables):
            lines += [
                "=" * 60,
                f"Section {i}: {table.section_title}",
                f"  table_found:   {table.table_found}",
                f"  table_chars:   {table.table_char_count:,}",
                f"  section_chars: {table.section_char_count:,}",
                "",
                "--- TABLE TEXT (primary LLM input) ---",
                table.table_text,
                "",
            ]

        out = _out(f"{name}_stage4_tables.txt")
        out.write_text("\n".join(lines), encoding="utf-8")
        assert out.stat().st_size > 0, f"Stage 4 output for {name} is empty"


# ---------------------------------------------------------------------------
# Stage 5a — bond anchors
# ---------------------------------------------------------------------------


class TestWriteStage5a:
    """Write bond anchor extraction results: bond name and validated ISINs."""

    @requires_pdf
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_write_anchors(self, name: str) -> None:
        _skip_if_missing(name)
        anchors = _get_anchors(name)

        data = [
            {
                "section_index": i,
                "bond_name": anchor.bond_name,
                "isins": anchor.isins,
                "raw_isin_candidates": anchor.raw_isin_candidates,
            }
            for i, anchor in enumerate(anchors)
        ]

        out = _out(f"{name}_stage5a_anchors.json")
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        assert out.stat().st_size > 0, f"Stage 5a output for {name} is empty"


# ---------------------------------------------------------------------------
# Stage 6 — XML assembly (synthetic GeoPark data, no Ollama required)
# ---------------------------------------------------------------------------


class TestWriteStage6Synthetic:
    """Write assembled BDT XML for a synthetic GeoPark bond (no Ollama needed).

    Useful as a fast structural check that doesn't require LLM extraction.
    """

    def test_write_geopark_xml(self) -> None:
        from pipeline.stage6_assemble import assemble

        result = ExtractionResult(
            anchor_bond_name="GeoPark Limited 5.500% Senior Notes due 2027",
            anchor_isins=["USG38327AB13"],
            fields={
                "isin": "USG38327AB13",
                "cusip": "G38327AB1",
                "common_code": "233279448",
                "aggregate_nominal_amount": 150_000_000.0,
                "specified_denomination": 200_000.0,
                "integral_multiples": 1_000.0,
                "issue_price": 100.0,
                "interest_rate": 0.055,
                "pricing_date": "2021-07-13",
                "issue_date": "2021-07-16",
                "settlement_date": "2021-07-16",
                "maturity_date": "2027-01-17",
                "interest_commencement_date": "2021-07-17",
                "first_interest_payment_date": "2022-01-17",
                "interest_type": "FIXED",
                "interest_payment_frequency": "SEMIANNUALLY",
                "day_count_fraction": "30/360",
                "business_day_convention": "FOLLOWING_UNADJUSTED",
                "business_day_center": "NEW_YORK",
                "issuance_type": "STANDALONE",
                "form_of_note": "REGISTERED",
                "status_of_note": "SENIOR_UNSECURED",
                "specified_currency": "USD",
                "governing_law": "NEW_YORK_LAW",
                "selling_restrictions": ["144A", "REGS_CAT2"],
                "issuer_name": "GeoPark Limited",
            },
            parties=[
                PartyInfo(name="GeoPark Limited", role="ISSUER"),
                PartyInfo(name="Citibank N.A.", role="TRUSTEE"),
            ],
            status="done_partial",  # No real LEIs → done_partial expected
            manufacturer_target_market=["NOT_APPLICABLE"],
        )

        assembly = assemble(result)
        out = _out("geopark_stage6_synthetic.xml")
        out.write_bytes(assembly.xml_bytes)

        summary_lines = [
            "=== Stage 6 Assembly: GEOPARK (synthetic) ===",
            f"filename:   {assembly.filename}",
            f"xsd_valid:  {assembly.xsd_valid}",
            f"status:     {assembly.status}",
            "",
            "XSD errors:" if assembly.xsd_errors else "XSD errors: none",
            *(f"  - {e}" for e in assembly.xsd_errors),
            "",
            "Assembly warnings:",
            *(f"  - {w}" for w in assembly.warnings),
        ]
        _out("geopark_stage6_synthetic_summary.txt").write_text(
            "\n".join(summary_lines), encoding="utf-8"
        )
        assert out.stat().st_size > 0, "Stage 6 synthetic XML output is empty"


# ---------------------------------------------------------------------------
# Stage 5 (full LLM) — extraction on all real PDF fixtures
# ---------------------------------------------------------------------------


class TestWriteStage5Full:
    """Run full LLM extraction (stages 5a→5c) on every fixture.

    Writes one JSON file per fixture with all extracted fields, parties,
    warnings, and status for every bond section found in that PDF.
    Requires both PDF fixtures and a running Ollama instance.
    """

    @requires_pdf
    @requires_ollama
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_write_extraction(self, name: str) -> None:
        _skip_if_missing(name)
        extractions = _get_extraction(name)
        tables = _get_tables(name)

        sections_data = []
        for i, (result, table) in enumerate(zip(extractions, tables, strict=True)):
            sections_data.append(
                {
                    "section_index": i,
                    "section_title": table.section_title,
                    "anchor_bond_name": result.anchor_bond_name,
                    "anchor_isins": result.anchor_isins,
                    "status": result.status,
                    "fields": result.fields,
                    "parties": [
                        {
                            "name": p.name,
                            "role": p.role,
                            "lei": p.lei,
                            "lei_resolved": p.lei_resolved,
                        }
                        for p in result.parties
                    ],
                    "warnings": [
                        {"field": w.field_name, "group": w.group, "message": w.message}
                        for w in result.warnings
                    ],
                    "manufacturer_target_market": result.manufacturer_target_market,
                }
            )

        out = _out(f"{name}_stage5_extraction.json")
        out.write_text(
            json.dumps({"fixture": name, "sections": sections_data}, indent=2, default=str),
            encoding="utf-8",
        )
        assert out.stat().st_size > 0, f"Stage 5 extraction output for {name} is empty"


# ---------------------------------------------------------------------------
# Stage 6 (full pipeline) — XML assembly on all real PDF fixtures
# ---------------------------------------------------------------------------


class TestWriteStage6All:
    """Assemble BDT XML from real LLM-extracted data for every fixture.

    Writes one XML per bond section and a combined summary text file per
    fixture.  Requires both PDF fixtures and a running Ollama instance.
    """

    @requires_pdf
    @requires_ollama
    @pytest.mark.parametrize("name", _FIXTURES)
    def test_write_assembly(self, name: str) -> None:
        _skip_if_missing(name)
        assemblies = _get_assembly(name)
        tables = _get_tables(name)

        multi = len(assemblies) > 1
        for i, assembly in enumerate(assemblies):
            suffix = f"_section{i}" if multi else ""
            xml_out = _out(f"{name}{suffix}_stage6.xml")
            xml_out.write_bytes(assembly.xml_bytes)

        summary_lines = [
            f"=== Stage 6 Assembly: {name.upper()} ===",
            f"Sections: {len(assemblies)}",
            "",
        ]
        for i, (assembly, table) in enumerate(zip(assemblies, tables, strict=True)):
            summary_lines += [
                "=" * 60,
                f"Section {i}: {table.section_title}",
                f"  filename:  {assembly.filename}",
                f"  xsd_valid: {assembly.xsd_valid}",
                f"  status:    {assembly.status}",
                "",
                "  XSD errors:" if assembly.xsd_errors else "  XSD errors: none",
                *(f"    - {e}" for e in assembly.xsd_errors),
                "",
                "  Assembly warnings:",
                *(f"    - {w}" for w in assembly.warnings),
                "",
            ]

        out = _out(f"{name}_stage6_summary.txt")
        out.write_text("\n".join(summary_lines), encoding="utf-8")
        assert len(assemblies) > 0, f"No assembly results for {name}"
