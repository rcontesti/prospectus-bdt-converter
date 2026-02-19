"""
Stage 2 — PDF Parsing

Extracts text from a PDF using pymupdf (fitz).  Returns a list of Page objects,
each carrying raw text and a list of detected blocks (heading / paragraph / table).

pymupdf is used for MVP because it is fast and preserves enough layout for
heading detection and table scanning.  It works on standard text-based PDFs
(the overwhelming majority of bond prospectuses).  Scanned PDFs that require
OCR are flagged and deferred to a future docling/easyocr integration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pymupdf  # fitz

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


BlockType = Literal["heading", "paragraph", "table_row", "unknown"]


@dataclass
class Block:
    """A single logical text block on a page."""

    type: BlockType
    text: str
    # pymupdf bounding box (x0, y0, x1, y1) in points
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class Page:
    """Text content of a single PDF page."""

    page_number: int  # 1-indexed
    raw_text: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """Result of Stage 2."""

    path: Path
    page_count: int
    pages: list[Page]
    is_scanned: bool = False  # True if OCR would be needed

    @property
    def full_text(self) -> str:
        """All pages concatenated, separated by form-feed."""
        return "\f".join(p.raw_text for p in self.pages)


# ---------------------------------------------------------------------------
# Heuristics for block classification
# ---------------------------------------------------------------------------

# A heading is a short line (≤120 chars) that appears as its own block,
# often in a larger font.  We also check pymupdf's span flags for bold text.
_MAX_HEADING_LEN = 120

# Patterns that strongly suggest a table row: contains a tab, or multiple
# consecutive spaces suggesting column alignment, or starts with a bullet.
_TABLE_ROW_PAT = re.compile(r"\t|  {3,}|^\s*[•\-–—]\s")


def _classify_block(text: str, font_size: float, page_font_sizes: list[float]) -> BlockType:
    """Heuristic classification of a text block."""
    stripped = text.strip()
    if not stripped:
        return "unknown"

    # Headings: short, and font size above the page median
    median_size = sorted(page_font_sizes)[len(page_font_sizes) // 2] if page_font_sizes else 11.0
    if (
        len(stripped) <= _MAX_HEADING_LEN
        and "\n" not in stripped.strip()
        and font_size > median_size * 1.05
    ):  # noqa: E501
        return "heading"

    # Table rows: contain tab characters or multiple-space alignment
    if _TABLE_ROW_PAT.search(stripped):
        return "table_row"

    return "paragraph"


# ---------------------------------------------------------------------------
# Main parsing function
# ---------------------------------------------------------------------------

# Threshold below which a page is considered likely scanned (very little text)
_MIN_TEXT_CHARS_PER_PAGE = 100


def parse_pdf(pdf_path: str | Path) -> ParsedDocument:
    """
    Parse a PDF file and return a ParsedDocument.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        ParsedDocument with one Page per PDF page.

    Raises:
        FileNotFoundError: if the PDF does not exist.
        RuntimeError: if pymupdf cannot open the file.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(f"Cannot open PDF '{pdf_path}': {exc}") from exc

    pages: list[Page] = []
    scanned_page_count = 0

    for page_idx in range(len(doc)):
        fitz_page = doc[page_idx]
        page_number = page_idx + 1

        # Extract text as a dictionary so we get font size information
        raw_dict = fitz_page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)

        # Collect all spans to compute per-page font size distribution
        all_spans: list[dict] = []
        for block in raw_dict.get("blocks", []):
            for line in block.get("lines", []):
                all_spans.extend(line.get("spans", []))

        page_font_sizes = [s["size"] for s in all_spans if s.get("size", 0) > 0]

        # Build plain text (used for all downstream stages)
        raw_text = fitz_page.get_text("text")

        # Detect likely-scanned pages
        if len(raw_text.strip()) < _MIN_TEXT_CHARS_PER_PAGE:
            scanned_page_count += 1

        # Build classified blocks from pymupdf block list
        classified_blocks: list[Block] = []
        for raw_block in raw_dict.get("blocks", []):
            if raw_block.get("type") != 0:  # type 0 = text; type 1 = image
                continue

            block_lines = raw_block.get("lines", [])
            if not block_lines:
                continue

            # Concatenate all text in this block
            block_text = "\n".join(
                "".join(s["text"] for s in line["spans"]) for line in block_lines
            ).strip()

            if not block_text:
                continue

            # Representative font size: max size in this block (headings use largest font)
            block_font_sizes = [
                s["size"] for line in block_lines for s in line["spans"] if s.get("size", 0) > 0
            ]
            rep_size = max(block_font_sizes) if block_font_sizes else 11.0

            bbox_raw = raw_block.get("bbox")
            bbox = tuple(bbox_raw) if bbox_raw else None

            btype = _classify_block(block_text, rep_size, page_font_sizes)
            classified_blocks.append(Block(type=btype, text=block_text, bbox=bbox))

        pages.append(
            Page(
                page_number=page_number,
                raw_text=raw_text,
                blocks=classified_blocks,
            )
        )

    doc.close()

    # Flag document as scanned if more than 20% of pages have very little text
    is_scanned = scanned_page_count > len(pages) * 0.20

    return ParsedDocument(
        path=pdf_path,
        page_count=len(pages),
        pages=pages,
        is_scanned=is_scanned,
    )
