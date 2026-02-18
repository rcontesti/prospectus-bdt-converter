"""Shared pytest fixtures and markers for the BDT converter test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "PDF"

PDF_PATHS: dict[str, Path] = {
    "geopark": DATA_DIR / "USG38327AB13_OC_EN_2.PDF",
    "edenor": DATA_DIR / "USP3710FAU86_OC_EN.PDF",
    "csn": DATA_DIR / "USL21779AD28_OC_EN_3.pdf",
}

# ---------------------------------------------------------------------------
# Fixture expectations (page counts, minimum sections, etc.)
# ---------------------------------------------------------------------------

FIXTURE_CATALOG: dict[str, dict] = {
    "geopark": {
        "path": PDF_PATHS["geopark"],
        "page_count": 191,
        "min_sections": 1,
        "issuer": "GeoPark",
    },
    "edenor": {
        "path": PDF_PATHS["edenor"],
        "page_count": 154,
        "min_sections": 1,
        "issuer": "EDENOR",
    },
    "csn": {
        "path": PDF_PATHS["csn"],
        "page_count": 78,
        "min_sections": 2,
        "issuer": "CSN Resources",
    },
}


# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------


def _pdf_available(name: str) -> bool:
    return PDF_PATHS.get(name, Path("/missing")).exists()


requires_pdf = pytest.mark.requires_pdf
requires_ollama = pytest.mark.requires_ollama
requires_network = pytest.mark.requires_network


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip tests marked with requires_pdf when fixtures are absent."""
    for item in items:
        if "requires_pdf" in item.keywords:
            # Check if any specific fixture is referenced in parametrize ids
            # Default: skip if the geopark PDF (simplest fixture) is missing
            if not _pdf_available("geopark"):
                item.add_marker(pytest.mark.skip(reason="PDF fixtures not present in data/PDF/"))


# ---------------------------------------------------------------------------
# Session-scoped expensive fixtures (parse once, reuse everywhere)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def geopark_doc():
    """Parse the GeoPark PDF once per test session."""
    if not _pdf_available("geopark"):
        pytest.skip("GeoPark PDF not present")
    from pipeline.stage2_parse import parse_pdf

    return parse_pdf(PDF_PATHS["geopark"])


@pytest.fixture(scope="session")
def geopark_sections(geopark_doc):
    """Find bond sections in GeoPark (session-scoped)."""
    from pipeline.stage3_find import find_bond_sections

    return find_bond_sections(geopark_doc)


@pytest.fixture(scope="session")
def geopark_table(geopark_sections):
    """Detect summary table for the first GeoPark section (session-scoped)."""
    from pipeline.stage4_table import detect_summary_table

    assert len(geopark_sections) >= 1, "GeoPark should have at least one bond section"
    return detect_summary_table(geopark_sections[0])
