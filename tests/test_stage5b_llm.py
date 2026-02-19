"""Tests for Stage 5b — Grouped LLM Extraction.

Unit tests cover prompt construction (no LLM needed).
Integration tests with Ollama are skipped via requires_ollama marker.
"""

from __future__ import annotations

import pytest

from pipeline.llm_backend import OllamaBackend
from pipeline.stage5a_anchor import BondAnchor
from pipeline.stage5b_llm import (
    _build_group_prompt,
    _build_system_prompt,
    _should_extract_amortization,
    GroupExtractionResult,
)
from bdt.enums import FIELD_GROUPS
from tests.conftest import requires_ollama, requires_pdf


# ---------------------------------------------------------------------------
# Prompt construction unit tests (no LLM needed)
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """Unit tests for system prompt construction."""

    def test_contains_extraction_instruction(self):
        anchor = BondAnchor(bond_name="Test", isins=["XS1234567890"], raw_isin_candidates=[])
        prompt = _build_system_prompt(anchor)
        assert "extract" in prompt.lower()
        assert "JSON" in prompt

    def test_includes_isin_when_present(self):
        anchor = BondAnchor(bond_name="Test", isins=["XS1234567890"], raw_isin_candidates=[])
        prompt = _build_system_prompt(anchor)
        assert "XS1234567890" in prompt

    def test_no_isin_clause_when_empty(self):
        anchor = BondAnchor(bond_name="Test", isins=[], raw_isin_candidates=[])
        prompt = _build_system_prompt(anchor)
        assert "ISIN(s)" not in prompt


class TestGroupPrompt:
    """Unit tests for group prompt construction."""

    def test_contains_group_description(self):
        anchor = BondAnchor(bond_name="Test", isins=["XS1234567890"], raw_isin_candidates=[])
        group_def = FIELD_GROUPS["identifiers"]
        prompt = _build_group_prompt("identifiers", group_def, "some text", anchor)
        assert "Security identifiers" in prompt

    def test_contains_field_names(self):
        anchor = BondAnchor(bond_name="Test", isins=[], raw_isin_candidates=[])
        group_def = FIELD_GROUPS["dates"]
        prompt = _build_group_prompt("dates", group_def, "some text", anchor)
        assert "pricing_date" in prompt
        assert "maturity_date" in prompt

    def test_contains_table_text(self):
        anchor = BondAnchor(bond_name="Test", isins=[], raw_isin_candidates=[])
        group_def = FIELD_GROUPS["identifiers"]
        table_text = "ISIN: XS2385150334\nMaturity: 2027"
        prompt = _build_group_prompt("identifiers", group_def, table_text, anchor)
        assert "XS2385150334" in prompt

    def test_all_groups_produce_prompts(self):
        anchor = BondAnchor(bond_name="Test", isins=["XS0000000000"], raw_isin_candidates=[])
        for group_name, group_def in FIELD_GROUPS.items():
            prompt = _build_group_prompt(group_name, group_def, "text", anchor)
            assert len(prompt) > 50, f"Group '{group_name}' prompt too short"


class TestAmortizationDetection:
    """Unit tests for amortization trigger logic."""

    def test_keyword_triggers(self):
        assert _should_extract_amortization("Bond amortizes over 3 years", None)
        assert _should_extract_amortization("installment repayment", None)

    def test_no_keyword_no_trigger(self):
        assert not _should_extract_amortization("fixed rate bullet bond", None)

    def test_issuance_result_triggers(self):
        issuance = GroupExtractionResult(
            group_name="issuance",
            fields={"redemption_payment_basis": "INSTALLMENT"},
        )
        assert _should_extract_amortization("some text", issuance)

    def test_issuance_par_no_trigger(self):
        issuance = GroupExtractionResult(
            group_name="issuance",
            fields={"redemption_payment_basis": "PAR"},
        )
        assert not _should_extract_amortization("some text", issuance)


# ---------------------------------------------------------------------------
# Integration tests (requires Ollama)
# ---------------------------------------------------------------------------


class TestOllamaIntegration:
    """Integration tests that require a running Ollama instance."""

    @requires_ollama
    @requires_pdf
    def test_extract_identifiers_geopark(self, geopark_table):
        from pipeline.stage5a_anchor import extract_anchor
        from pipeline.stage5b_llm import extract_fields

        anchor = extract_anchor(geopark_table)
        backend = OllamaBackend()  # default localhost:11434
        result = extract_fields(geopark_table, anchor, backend)
        assert "identifiers" in result.groups
        assert len(result.groups["identifiers"].fields) > 0
