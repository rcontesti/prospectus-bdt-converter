"""
Stage 5a — Bond Anchor Extraction

Extracts the primary bond identity (name + ISINs) from a bond section using
regex only — no LLM call.  The anchor is used to disambiguate subsequent
LLM prompts ("Extract fields for the bond with ISIN XS2385150334…").

ISIN validation uses the ISO 6166 Luhn check digit algorithm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.stage4_table import TableDetectionResult

# ISO 6166 ISIN pattern: 2 alpha country code + 9 alphanumeric + 1 check digit
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b")


@dataclass
class BondAnchor:
    """Identity of a bond extracted from a section."""

    bond_name: str
    isins: list[str]  # validated ISINs (checksum-passing)
    raw_isin_candidates: list[str] = field(default_factory=list)  # all regex matches


def _isin_checksum_valid(isin: str) -> bool:
    """
    Validate an ISIN using the ISO 6166 Luhn check digit.

    Steps:
    1. Convert letters to digits (A=10, B=11, …, Z=35).
    2. Concatenate all digits into a single string.
    3. Apply the Luhn algorithm — the result must be 0.
    """
    if len(isin) != 12:
        return False

    digits = ""
    for ch in isin:
        if ch.isdigit():
            digits += ch
        elif ch.isalpha():
            digits += str(ord(ch) - ord("A") + 10)
        else:
            return False

    # Luhn on the digit string
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n

    return total % 10 == 0


def extract_anchor(table_result: TableDetectionResult) -> BondAnchor:
    """
    Extract the bond anchor (name + ISINs) from a table detection result.

    Searches the table text first (higher signal density), then falls back
    to the full section text.  Only ISINs passing the ISO 6166 checksum
    are kept.

    Args:
        table_result: Output from Stage 4.

    Returns:
        BondAnchor with validated ISINs and bond name.
    """
    # Search table text first, then full section as fallback
    raw_candidates: list[str] = []
    seen: set[str] = set()

    for text in (table_result.table_text, table_result.full_section_text):
        for match in _ISIN_RE.finditer(text):
            candidate = match.group(1)
            if candidate not in seen:
                seen.add(candidate)
                raw_candidates.append(candidate)

    # Validate checksums
    valid_isins = [isin for isin in raw_candidates if _isin_checksum_valid(isin)]

    # Bond name: use section title; if generic, try to extract from table
    bond_name = table_result.section_title
    if _is_generic_title(bond_name):
        extracted = _extract_bond_name(table_result.table_text)
        if extracted:
            bond_name = extracted

    return BondAnchor(
        bond_name=bond_name,
        isins=valid_isins,
        raw_isin_candidates=raw_candidates,
    )


def _is_generic_title(title: str) -> bool:
    """Return True if the section title is too generic to identify the bond."""
    generic_patterns = [
        "description of the notes",
        "description of the bonds",
        "terms and conditions",
        "description of the securities",
        "summary of terms",
    ]
    lower = title.strip().lower()
    return any(lower == pat or lower.startswith(pat) for pat in generic_patterns)


def _extract_bond_name(table_text: str) -> str | None:
    """Try to extract a specific bond name from the first lines of the table text."""
    lines = table_text.strip().splitlines()
    for line in lines[:10]:
        stripped = line.strip()
        # Look for lines containing percentage + "Notes" or "Bonds"
        if re.search(r"\d+\.\d+%?\s+.*(?:Notes|Bonds|Securities)", stripped, re.IGNORECASE):
            return stripped
    return None
