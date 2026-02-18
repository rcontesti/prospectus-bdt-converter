"""
Stage 3 — Section Finding

Scans the parsed document for headings that introduce bond term sections.
Returns one BondSection per matched heading — one per bond found in the document.

Approach: heading detection (not TOC parsing).
- Scan all blocks classified as "heading" (or short paragraph blocks) across all pages.
- Fuzzy-match each candidate against the target heading list.
- For each match, collect all text from that heading to the next major heading.

Why not TOC: TOC page numbers use the document's internal pagination (S-1, S-2, …)
which does not match the PDF page index.  Off-by-N errors are common and hard to
detect.  Heading detection is simpler and more robust for MVP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from pipeline.stage2_parse import ParsedDocument, Page, Block


# ---------------------------------------------------------------------------
# Target headings (case-insensitive, fuzzy-matched)
# ---------------------------------------------------------------------------

TARGET_HEADINGS: list[str] = [
    "Description of the Notes",
    "Description of the Bonds",
    "Terms and Conditions of the Notes",
    "Terms and Conditions of the Bonds",
    "Terms and Conditions",
    "Description of the Securities",
    "Description of the New Securities",
    "Description of the New Notes",
    "Summary of Terms",                    # some EM OMs lead with this
    "Summary of the Terms",
]

# Fuzzy match score threshold (0–100).
# token_sort_ratio handles word reordering and case differences well.
# 85 is enough to match "DESCRIPTION OF NOTES" ↔ "Description of the Notes"
# while excluding most cross-references and noise.
_FUZZY_THRESHOLD = 85

# Headings are short, single-line, and isolated.
# Cross-references ("see Description of Notes—Covenants") are excluded by the max limit.
# Very short strings ("i", "as of") are excluded by the min limit.
_MIN_HEADING_CHARS = 8
_MAX_HEADING_CHARS = 90

# ---------------------------------------------------------------------------
# Major-section headings that terminate a bond section.
# These are headings we do NOT want to include in the bond section text.
# Ordered roughly by how frequently they appear after bond terms.
# ---------------------------------------------------------------------------

SECTION_TERMINATORS: list[str] = [
    "Use of Proceeds",
    "Capitalization",
    "Selected Financial",
    "Management's Discussion",
    "Management Discussion",
    "Business",
    "Risk Factors",
    "Taxation",
    "Tax Considerations",               # catches "CERTAIN TAX CONSIDERATIONS"
    "ERISA",
    "Plan of Distribution",
    "Underwriting",
    "Legal Matters",
    "Experts",
    "Auditors",
    "Financial Statements",
    "Index to Financial",
    "Appendix",
    "Annex",
    "Exhibit",
    "Glossary",
    "Defined Terms",
    "Form of",                          # e.g. "Form of Global Note"
    "Book-Entry",                       # e.g. "BOOK-ENTRY, DELIVERY AND FORM"
    "Clearing",                         # e.g. "CLEARING AND SETTLEMENT"
    "Transfer Restrictions",
    "Selling Restrictions",             # section heading, not the field
]

_TERMINATOR_THRESHOLD = 75


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class BondSection:
    """A section of the document that describes a single bond."""
    title: str                  # The matched heading text
    page_start: int             # Page number (1-indexed) where the heading was found
    page_end: int               # Last page included in this section
    text: str                   # Full concatenated text of this section
    match_score: float          # Fuzzy match score against the target heading
    target_matched: str         # Which target heading this matched


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_target_heading(text: str) -> tuple[bool, float, str]:
    """
    Return (matched, score, target) for the best fuzzy match against TARGET_HEADINGS.

    Matching strategy:
    - token_sort_ratio as primary: handles word reordering and case (e.g. "DESCRIPTION
      OF NOTES" ↔ "Description of the Notes").
    - partial_ratio as secondary but only for candidates in the allowed length window:
      handles extra words like "Description of the 5.500% Senior Notes".
    - Hard length gates (MIN/MAX) exclude trivial strings and long cross-references.
    - Requires NO embedded newlines: real headings are single lines.
    """
    stripped = text.strip()

    # Gate 1: length
    if len(stripped) < _MIN_HEADING_CHARS or len(stripped) > _MAX_HEADING_CHARS:
        return False, 0.0, ""

    # Gate 2: single line — headings do not span multiple lines
    if "\n" in stripped:
        return False, 0.0, ""

    best_score = 0.0
    best_target = ""
    lower = stripped.lower()

    for target in TARGET_HEADINGS:
        t_lower = target.lower()
        # Primary: token_sort_ratio (word order invariant, good for all-caps headings)
        score_sort = fuzz.token_sort_ratio(t_lower, lower)
        # Secondary: partial_ratio — only useful if candidate is longer than target
        # (e.g. "Description of the 5.500% Senior Notes" contains target)
        score_partial = fuzz.partial_ratio(t_lower, lower) if len(lower) >= len(t_lower) else 0
        score = max(score_sort, score_partial)
        if score > best_score:
            best_score = score
            best_target = target

    return best_score >= _FUZZY_THRESHOLD, best_score, best_target


def _is_terminator_heading(text: str) -> bool:
    """Return True if the heading signals the end of a bond terms section."""
    stripped = text.strip()
    if len(stripped) < _MIN_HEADING_CHARS or len(stripped) > _MAX_HEADING_CHARS:
        return False
    if "\n" in stripped:
        return False
    lower = stripped.lower()
    for term in SECTION_TERMINATORS:
        t_lower = term.lower()
        score_sort = fuzz.token_sort_ratio(t_lower, lower)
        # partial_ratio: catches "CERTAIN TAX CONSIDERATIONS" against "Tax Considerations"
        score_partial = fuzz.partial_ratio(t_lower, lower) if len(lower) >= len(t_lower) else 0
        if max(score_sort, score_partial) >= _TERMINATOR_THRESHOLD:
            return True
    return False


def _collect_section_text(
    pages: list[Page],
    start_page_idx: int,
    start_block_idx: int,
    end_page_idx: int,
    end_block_idx: int | None,
) -> str:
    """
    Collect all block text from (start_page_idx, start_block_idx) to
    (end_page_idx, end_block_idx exclusive).  Returns joined text.
    """
    parts: list[str] = []

    for pi in range(start_page_idx, end_page_idx + 1):
        page = pages[pi]
        block_start = start_block_idx if pi == start_page_idx else 0
        block_end = end_block_idx if (pi == end_page_idx and end_block_idx is not None) else len(page.blocks)

        for bi in range(block_start, block_end):
            block_text = page.blocks[bi].text.strip()
            if block_text:
                parts.append(block_text)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


def find_bond_sections(doc: ParsedDocument) -> list[BondSection]:
    """
    Scan a ParsedDocument for bond term sections.

    Returns a list of BondSection objects — one per matched heading.
    Multiple sections indicate a multi-bond prospectus.

    The returned sections are ordered by page_start (document order).

    **Design note — recall over precision:** Stage 3 is intentionally broad.
    Complex prospectuses produce false positive sections (risk factor headings,
    exchange offer summaries, etc.).  Stage 5a filters these by requiring a valid
    ISIN anchor — sections with no identifiable ISIN are skipped.
    """
    pages = doc.pages

    # --- Pass 1: find all candidate heading locations ---
    # Each entry: (page_idx, block_idx, block_text, score, target)
    hits: list[tuple[int, int, str, float, str]] = []

    for pi, page in enumerate(pages):
        for bi, block in enumerate(page.blocks):
            # Check all blocks ≤ _MAX_HEADING_CHARS; classification is a hint not a gate
            candidate = block.text.strip()
            if not candidate or len(candidate) > _MAX_HEADING_CHARS:
                continue
            matched, score, target = _is_target_heading(candidate)
            if matched:
                hits.append((pi, bi, candidate, score, target))

    if not hits:
        return []

    # --- Pass 2: deduplicate hits that are on consecutive pages/blocks ---
    # Keep the highest-score hit within a 3-page window of each other.
    deduped: list[tuple[int, int, str, float, str]] = []
    for hit in hits:
        if deduped and hit[0] - deduped[-1][0] <= 3:
            # Same window — keep the higher score
            if hit[3] > deduped[-1][3]:
                deduped[-1] = hit
        else:
            deduped.append(hit)

    # --- Pass 3: for each hit, collect text until the next major section ---
    sections: list[BondSection] = []

    for idx, (pi, bi, heading_text, score, target) in enumerate(deduped):
        # Determine where this section ends: either the start of the next hit
        # or the next terminator heading, whichever comes first.
        next_hit_pi = deduped[idx + 1][0] if idx + 1 < len(deduped) else len(pages)
        next_hit_bi = deduped[idx + 1][1] if idx + 1 < len(deduped) else 0

        # Scan forward from (pi, bi+1) to find a terminator
        term_pi = next_hit_pi
        term_bi: int | None = next_hit_bi if idx + 1 < len(deduped) else None

        for scan_pi in range(pi, min(next_hit_pi + 1, len(pages))):
            scan_page = pages[scan_pi]
            b_start = bi + 1 if scan_pi == pi else 0
            b_limit = next_hit_bi if scan_pi == next_hit_pi else len(scan_page.blocks)

            for scan_bi in range(b_start, b_limit):
                candidate = scan_page.blocks[scan_bi].text.strip()
                if not candidate or len(candidate) > _MAX_HEADING_CHARS:
                    continue
                if _is_terminator_heading(candidate):
                    term_pi = scan_pi
                    term_bi = scan_bi
                    break
            else:
                continue
            break

        # Collect all text in the section (excluding the heading itself)
        section_text = _collect_section_text(pages, pi, bi + 1, term_pi, term_bi)

        sections.append(BondSection(
            title=heading_text,
            page_start=pages[pi].page_number,
            page_end=pages[term_pi].page_number if term_pi < len(pages) else pages[-1].page_number,
            text=section_text,
            match_score=score,
            target_matched=target,
        ))

    return sections
