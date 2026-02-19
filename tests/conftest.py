"""Shared pytest fixtures and markers for the BDT converter test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "PDF"

PDF_PATHS: dict[str, Path] = {
    # Core fixtures (tested at every stage)
    "geopark": DATA_DIR / "USG38327AB13_OC_EN_2.PDF",
    "edenor": DATA_DIR / "USP3710FAU86_OC_EN.PDF",
    "csn": DATA_DIR / "USL21779AD28_OC_EN_3.pdf",
    # Extended fixtures (full pipeline output tests)
    "pdvsa": DATA_DIR / "PDVSA_XS0294364103.pdf",
    "buenos_aires": DATA_DIR / "Prospectus - 2021.pdf",
    "argentina_424b5": DATA_DIR / "REPUBLIC OF ARGENTINA Form 424B5 Filed 2020-08-17.pdf",
    "volcan": DATA_DIR / "USP98047AC08_PR_EN.pdf",
    "liquid_telecom": DATA_DIR / "XS2278474924_OC_EN_2.pdf",
    "argentina_gdp": DATA_DIR / "us_prospectus_and_prospectus_supplement.pdf",
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
        "min_sections": 1,  # 2023 + 2026 notes are in one "DESCRIPTION OF NOTES" section  # noqa: E501
        "issuer": "CSN Resources",
    },
    "pdvsa": {
        "path": PDF_PATHS["pdvsa"],
        "min_sections": 1,
        "issuer": "PDVSA",
    },
    "buenos_aires": {
        "path": PDF_PATHS["buenos_aires"],
        "min_sections": 1,
        "issuer": "Province of Buenos Aires",
    },
    "argentina_424b5": {
        "path": PDF_PATHS["argentina_424b5"],
        "min_sections": 1,
        "issuer": "Republic of Argentina",
    },
    "volcan": {
        "path": PDF_PATHS["volcan"],
        "min_sections": 1,
        "issuer": "Volcan",
    },
    "liquid_telecom": {
        "path": PDF_PATHS["liquid_telecom"],
        "min_sections": 1,
        "issuer": "Liquid Telecom",
    },
    "argentina_gdp": {
        "path": PDF_PATHS["argentina_gdp"],
        "min_sections": 1,
        "issuer": "Republic of Argentina (GDP-linked)",
    },
}


# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------


def _pdf_available(name: str) -> bool:
    return PDF_PATHS.get(name, Path("/missing")).exists()


def _ollama_available() -> bool:
    try:
        import httpx

        response = httpx.get("http://localhost:11434", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


requires_pdf = pytest.mark.requires_pdf
requires_ollama = pytest.mark.requires_ollama
requires_network = pytest.mark.requires_network

# Cache Ollama availability once per session (checked at collection time)
_ollama_up: bool | None = None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-skip tests whose external dependencies are absent."""
    global _ollama_up  # noqa: PLW0603
    for item in items:
        if "requires_pdf" in item.keywords and not _pdf_available("geopark"):
            item.add_marker(pytest.mark.skip(reason="PDF fixtures not present in data/PDF/"))
        if "requires_ollama" in item.keywords:
            if _ollama_up is None:
                _ollama_up = _ollama_available()
            if not _ollama_up:
                item.add_marker(pytest.mark.skip(reason="Ollama not running at localhost:11434"))


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
def geopark_table(geopark_doc, geopark_sections):
    """Detect summary table for the first GeoPark section (session-scoped)."""
    from pipeline.stage4_table import detect_summary_table

    assert len(geopark_sections) >= 1, "GeoPark should have at least one bond section"
    return detect_summary_table(geopark_sections[0], parsed_doc=geopark_doc)
