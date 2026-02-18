"""
Stage 4 — Summary Table Detection

Within each bond section (from Stage 3), locate the compact "key terms" block
that most prospectuses put at the beginning of the Description of the Notes.
This is the primary input for Stage 5 LLM extraction.

Approach:
1. Take the first 15% of the section text (the part most likely to contain the
   summary table).
2. Scan for a contiguous run of lines that looks like a structured terms table:
   lines with BDT keyword hits, typically formatted as "Label ... Value" pairs.
3. Return the detected table text as the primary LLM input.
4. If no table is found, return the full section text as fallback.

Why this matters: sending a 2-page key terms table to the LLM is far more
reliable than sending 40 pages of covenants.  Token cost also drops sharply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.stage3_find import BondSection


# ---------------------------------------------------------------------------
# BDT keyword signals — lines containing these are likely part of a terms table
# ---------------------------------------------------------------------------

_TABLE_KEYWORDS: list[str] = [
    "isin",
    "cusip",
    "common code",
    "maturity",
    "interest rate",
    "coupon",
    "principal amount",
    "nominal amount",
    "aggregate",
    "denomination",
    "currency",
    "issue price",
    "issue date",
    "settlement",
    "pricing date",
    "governing law",
    "listing",
    "form of",
    "clearing",
    "day count",
    "business day",
    "payment date",
    "interest payment",
    "first interest",
    "redemption",
    "trustee",
    "fiscal agent",
    "paying agent",
]

# Proportion of the section to scan for the table (first N% of characters)
_SCAN_FRACTION = 0.15

# A "table region" is a contiguous block of lines where at least this fraction
# of lines contain BDT keywords.
_TABLE_LINE_DENSITY = 0.30

# Minimum number of lines in a table region
_MIN_TABLE_LINES = 5

# Maximum number of lines we extend the table region (generous to capture
# all rows between keyword lines)
_MAX_GAP_LINES = 6


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TableDetectionResult:
    """Result of Stage 4."""
    section_title: str
    table_text: str          # compact key terms block (primary LLM input)
    full_section_text: str   # always provided as fallback
    table_found: bool        # False if we fell back to full section text
    table_char_count: int
    section_char_count: int


# A "table line" must: (a) have a BDT keyword AND (b) look like a label:value
# pair — i.e. be short and contain a structural separator (colon or tab).
# This distinguishes "Maturity Date: September 21, 2027" (table row) from a
# sentence like "The trustee is Bank of New York Mellon." (prose).
_MAX_TABLE_LINE_LEN = 200
# Structural separators: colon-space, tab, or multiple spaces (column alignment)
_SEPARATOR_PAT = re.compile(r":\s+|\t|  {2,}")


def _is_table_line(line: str) -> bool:
    """Return True if this line looks like a key-terms table row."""
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_TABLE_LINE_LEN:
        return False
    if not _has_keyword(stripped):
        return False
    # Must have at least one structural separator (colon, tab, or column spacing)
    return bool(_SEPARATOR_PAT.search(stripped))


def _has_keyword(line: str) -> bool:
    lower = line.lower()
    return any(kw in lower for kw in _TABLE_KEYWORDS)


def _find_table_region(lines: list[str]) -> tuple[int, int] | None:
    """
    Find the start and end line indices (inclusive) of the densest structured
    table region.

    Strategy:
    - Mark lines that are proper table rows (keyword + separator).
    - Find the longest contiguous run with at most _MAX_GAP_LINES between rows.
    - Require at least _MIN_TABLE_LINES table rows in the run.
    """
    n = len(lines)
    if n < _MIN_TABLE_LINES:
        return None

    # Mark which lines are proper table rows
    is_row = [_is_table_line(line) for line in lines]

    best_start = best_end = -1
    best_count = 0
    cur_start = -1
    cur_count = 0
    gap = 0

    for i, row in enumerate(is_row):
        if row:
            if cur_start < 0:
                cur_start = i
            cur_count += 1
            gap = 0
            cur_end = i
        else:
            if cur_start >= 0:
                gap += 1
                if gap > _MAX_GAP_LINES:
                    if cur_count > best_count:
                        best_count = cur_count
                        best_start = cur_start
                        best_end = cur_end
                    cur_start = -1
                    cur_count = 0
                    gap = 0

    # Final open run
    if cur_start >= 0 and cur_count > best_count:
        best_count = cur_count
        best_start = cur_start
        best_end = cur_end  # noqa: F821 — set in loop above

    if best_count < _MIN_TABLE_LINES:
        return None

    # Expand the region to include all lines between first and last row
    return best_start, best_end


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


def detect_summary_table(section: BondSection) -> TableDetectionResult:
    """
    Locate the compact key-terms block within a bond section.

    Scans the first _SCAN_FRACTION of the section text.  Returns a
    TableDetectionResult with the table text (or full text as fallback).
    """
    full_text = section.text
    section_len = len(full_text)

    # Scan only the first portion of the section
    scan_end = max(int(section_len * _SCAN_FRACTION), 3000)  # at least 3000 chars
    scan_text = full_text[:scan_end]

    lines = scan_text.splitlines()

    region = _find_table_region(lines)

    if region is not None:
        start_idx, end_idx = region
        # Extend end_idx: include a few more lines past the keyword region
        # (to capture values that appear on the line after the label)
        end_idx = min(end_idx + 3, len(lines) - 1)
        table_lines = lines[start_idx:end_idx + 1]
        table_text = "\n".join(table_lines).strip()

        return TableDetectionResult(
            section_title=section.title,
            table_text=table_text,
            full_section_text=full_text,
            table_found=True,
            table_char_count=len(table_text),
            section_char_count=section_len,
        )

    # Fallback: use the first _SCAN_FRACTION of the section
    # (still better than sending the full section — avoids the covenants bulk)
    return TableDetectionResult(
        section_title=section.title,
        table_text=scan_text.strip(),
        full_section_text=full_text,
        table_found=False,
        table_char_count=len(scan_text),
        section_char_count=section_len,
    )
