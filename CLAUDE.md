# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A pipeline that converts bond prospectus / indenture PDFs into **ICMA BDT v1.2 XML** files. Built CLI-first; runs as a Docker async API service in Phase 2 (batch PDFs in → batch XMLs out).

**Hard constraints:** open-source only, model-agnostic locally-runnable LLM, self-contained Docker.

## Build Order

```
Phase 1 (MVP):  python convert.py <input.pdf> --output <dir>/
Phase 2:        FastAPI wrapper around the same pipeline
```

Build and validate Stages 2–6 as a CLI tool before adding any API scaffolding.

## Pipeline (6 stages)

| Stage | Name | LLM | Status |
|-------|------|-----|--------|
| 1 | API + file-based job queue (FastAPI) — **deferred to Phase 2** | No | Not started |
| 2 | PDF parsing → structured text (pymupdf MVP, docling future) | No | Tested |
| 3 | Section Finding — heading detection | No | Tested |
| 4 | Summary Table Detection — find compact key terms block | No | Tested |
| 5 | BDT Field Extraction — Bond Anchor → Grouped LLM → Post-processor | Yes | Implemented + Tested |
| 6 | XML Assembly + XSD Validation (lxml) | No | Not started |

**Stage 3 — heading detection (not TOC):**
- Scan extracted text for short, isolated lines that fuzzy-match target patterns
- Target: "Description of the Notes", "Description of the Bonds", "Terms and Conditions of the Notes", "Terms and Conditions", "Description of the Securities", "Description of the New Securities"
- Take text from each match to the next major heading — that is one bond section
- Return ALL matches — every matched section is a separate bond candidate
- Output: ordered list of `(section_title, text)` tuples, one per bond found
- Why not TOC: TOC page numbers use internal pagination (S-1, S-2...) that doesn't match PDF page index → off-by-N errors

**Stage 4 — summary table detection:**
- Within each bond section, scan the first 15% of the text for a compact table-like block (consistent line structure, keywords: "Maturity Date", "Interest Rate", "ISIN", "Aggregate Principal Amount")
- Extract this block as the **primary LLM input** for Stage 5. Use full section text only as fallback.
- Why: a 2-page key terms table is far more reliable LLM input than 40 pages of legal prose

**Stage 5 — three sequential sub-steps:**

**5a — Bond Anchor** (run first, before any BDT field extraction):
```json
{ "bond_name": "...", "isins": ["XS...", "US..."] }
```
Returned ISINs are embedded in all subsequent prompts: *"Extract the following fields for the bond with ISIN XS2385150334. Ignore all other bonds or ISINs mentioned in the text."* This resolves the many-ISIN ambiguity.

**5b — Grouped LLM extraction** (one prompt per group, JSON output enforced via backend):
- Identifiers: ISIN, CUSIP, Common Code, SEDOL
- Amounts: AggregateNominalAmount, SpecifiedDenomination, IntegralMultiples, SpecifiedCurrency
- Dates: PricingDate, IssueDate, SettlementDate, MaturityDate, InterestCommencementDate
- Interest: InterestType, InterestRate, InterestPaymentFrequency, DayCountFraction, BusinessDayConvention, BusinessDayCenter — **enum values listed inline in prompt**
- Issuance: IssuanceType, IssuePrice, FormOfNote, StatusOfNote, GoverningLaw — **enum values listed inline in prompt**
- Parties: Issuer, lead managers, trustee, paying agent, fiscal agent (names only — LEI resolved in 5c)
- Selling restrictions: SellingRestrictions, PRIIPsRestriction — **enum values listed inline in prompt**
- Amortization: stepDate + stepValue pairs (only if bond is amortizing)
- `ManufacturerTargetMarket` is **not sent to LLM** — set by rule in 5c

**5c — Deterministic post-processing** (normalization only, no interpretation):
| Input | Action |
|-------|--------|
| Date strings | `dateutil` → ISO 8601 (`2030-01-09`) |
| Amount strings | Strip symbols → float (`500000000.0`) |
| ISIN strings | Validate 12-char format + ISO 6166 checksum |
| Enum value not in allowed list | Null + flag for review |
| Party names | GLEIF API → resolve LEI. On miss: placeholder + flag |
| `ManufacturerTargetMarket` | If SellingRestrictions contains `144A` or `REGS_CAT2` but no EU/UK MiFID → `NOT_APPLICABLE` |
| Any required field = null | Mark bond as `done_partial` |

**Stage 6 — output modes:**
- `done_valid` — all required fields extracted, XSD-valid
- `done_partial` — one or more required fields missing; output returned with `<ValidationWarnings>` block; never fails entirely due to missing fields
- N > 1 bonds in a PDF → result is a ZIP of N XMLs named by primary ISIN

## BDT Schema — Critical Constraints for Extraction

XSD files: `.docs/ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02/`

**Namespace:** `urn:icma:xsd:ICMABondDataTaxonomy`

**Required fields that MUST be present for a valid document:**
- Issuance: `IssuanceType`, `SpecifiedDenomination`, `SpecifiedCurrency`, `PricingDate`, `IssueDate`, `SettlementDate`, `IssuePrice`, `Listing` (1+), `GoverningLaw`, `SellingRestrictions`, `ManufacturerTargetMarket` (1+)
- Product: `FormOfNote`, `StatusOfNote`, `AggregateNominalAmount`, `MaturityDate`, `InterestPayment`, `DayCountFraction`, `BusinessDayConvention`, `BusinessDayCenter`
- InterestPayment requires: `InterestType`, `InterestCommencementDate`, `InterestPayments`
- InterestPayments requires: `InterestPaymentFrequency`, `PayableDate` (1..4 with Day+Month), `FirstPayment` (with PaymentDate)

**Enum constraints the LLM must output exactly** (strictly validated by XSD):
- `IssuanceType`: PROGRAMME | STANDALONE
- `InterestType`: FIXED | FLOATING | ZERO_COUPON | INDEX_LINKED_INTEREST
- `InterestPaymentFrequency`: ANNUALLY | SEMIANNUALLY | QUARTERLY | NONE
- `DayCountFraction`: ICMA_ACT/ACT | ISDA_ACT/ACT | 30/360 | 30/365 | ACT/360 | ACT/365
- `BusinessDayConvention`: FOLLOWING_UNADJUSTED | PRECEDING | MODIFIED_FOLLOWING_ADJUSTED
- `BusinessDayCenter`: TARGET | TARGET2 | FRANKFURT | NEW_YORK | LUXEMBOURG  ← only 5 options
- `GoverningLaw`: AUSTRIAN_LAW | BELGIAN_LAW | CANADIAN_LAW | DANISH_LAW | DUTCH_LAW | ENGLISH_LAW | FINISH_LAW | FRENCH_LAW | GERMAN_LAW | ITALIAN_LAW | LUXEMBOURG_LAW | NEW_SOUTH_WALES_LAW | NEW_YORK_LAW | ONTARIO_LAW | SPANISH_LAW  ← only 15 options
- `FormOfNote`: BEARER | REGISTERED | DEMATERIALISED | BOOK_ENTRY | FED_BOOK_ENTRY | (and 9 other variants — see enums XSD)
- `StatusOfNote`: SENIOR_SECURED | SENIOR_UNSECURED | SENIOR_PREFERRED | SENIOR_NON_PREFERRED | SUBORDINATED
- `SellingRestrictionCode`: REGS_CAT1 | REGS_CAT2 | REGS_CAT3 | 144A | TEFRA_C | TEFRA_D | TEFRA_NA | SEC_REG | NOT_APPLICABLE
- `ClearingSettlementSystem`: CLEARSTREAM_BANKING_FRANKFURT | DTCC | EUROCLEAR_BANK_SA/NV | CLEARSTREAM_BANKING_S.A. | CENTRAL_MONEY_MARKETS_UNIT
- `RedemptionPaymentBasisType`: PAR | PARTLY_PAID | INDEX_LINKED_INTEREST | INSTALLMENT | DUAL_CURRENCY
- `RatingAgency`: FITCH | MOODYS | SP | DBRS
- `ManufacturerTargetMarket`: EU_MIFIDII_PROF_AND_ECPS | EU_MIFIR_PROF_AND_ECPS | UK_MIFIR_PROF_AND_ECPS | EU_MIFIDII_RETAIL_PROF_ECPS | UK_MIFIR_RETAIL_PROF_ECPS | NOT_APPLICABLE

**Party cross-referencing:** Parties use XML ID/IDREF (`PID` attribute). Each `PartyRole` has `<PartyID PID="LEI-{lei}"/>` referencing a `<Party PID="LEI-{lei}">` element.

## Known BDT Gaps (handle these explicitly)

| Gap | Workaround |
|-----|-----------|
| No amortization schedule | Use `RedemptionPaymentBasis=INSTALLMENT` + custom `<AmortizationSchedule>` extension v1.0 |
| No step-up / step-down coupon schedule | Custom `<StepCouponSchedule>` extension (planned v1.0) |
| `BusinessDayCenter` missing Buenos Aires, Tokyo, etc. | Use `NEW_YORK` for USD bonds |
| `GoverningLaw` missing Argentinian, Singapore law | Use `NEW_YORK_LAW` for international tranche |
| `ClearingSettlementSystem` missing Caja de Valores, CDP | Use `DTCC` for 144A tranche |
| `RatingAgency` only 4 values | Free text for others |

## Extension Framework

Namespace pattern: `urn:bdt-ext:{name}:v{major}`. Two levels of placement:

1. `<ext:ExtensionManifest>` lives at the outer `<BDTDocument>` wrapper level, **sibling of `<bdt:Document>`** — the ICMA XSD sees only a valid `<bdt:Document>` child
2. Extension data elements live inside relevant BDT elements using their own namespace

**Output document structure:**
```xml
<BDTDocument xmlns:bdt="urn:icma:xsd:ICMABondDataTaxonomy"
             xmlns:ext="urn:bdt-ext:manifest:v1">
  <bdt:Document>
    <bdt:ICMABondDataTaxonomy>
      <!-- standard BDT — independently XSD-valid -->
    </bdt:ICMABondDataTaxonomy>
  </bdt:Document>
  <ext:ExtensionManifest>
    <ext:Extension name="amortization" version="1.0" namespace="urn:bdt-ext:amortization:v1"/>
    <ext:Extension name="step-coupon" version="1.0" namespace="urn:bdt-ext:step-coupon:v1"/>
  </ext:ExtensionManifest>
</BDTDocument>
```

**Amortization extension v1.0** (`urn:bdt-ext:amortization:v1`): when `RedemptionPaymentBasisType = INSTALLMENT`, append inside `<Product>`. Each `<step>` = outstanding notional *after* payment on `stepDate`. FpML `notionalStepSchedule` is the design reference:
```xml
<AmortizationSchedule xmlns="urn:bdt-ext:amortization:v1">
  <step><stepDate>2026-08-21</stepDate><stepValue currency="USD">1000000</stepValue></step>
  <step><stepDate>2027-08-21</stepDate><stepValue currency="USD">0</stepValue></step>
</AmortizationSchedule>
```

**Step-up coupon extension v1.0** (`urn:bdt-ext:step-coupon:v1`): planned. Each `<step>` = rate in effect from `stepDate` forward:
```xml
<StepCouponSchedule xmlns="urn:bdt-ext:step-coupon:v1">
  <step><stepDate>2024-08-21</stepDate><rate>0.0875</rate></step>
  <step><stepDate>2026-08-21</stepDate><rate>0.1000</rate></step>
</StepCouponSchedule>
```

ACTUS is noted for future algorithmic schedule derivation/validation.

## Dual-ISIN / Multi-Bond Logic

**Dual-ISIN (same economic bond, two markets):** a 144A ISIN + Reg S ISIN represent one bond. Produce **one BDT XML** with both ISINs in `<SecurityIdentifierList>`, both clearing systems in `<ClearingSettlementSystem>`, both selling restrictions in `<SellingRestrictions>`. File named after Reg S ISIN for international bonds. If tranches have materially different terms (different amounts, different maturity), treat as separate bonds.

**Multi-bond prospectus:** Stage 3 returns N section tuples → Stage 5 runs N times → Stage 6 produces N XMLs → Phase 2 API result is a ZIP.

## LLM Backend Architecture

**File:** `pipeline/llm_backend.py`

Stage 5b calls `backend.complete(system_prompt, user_prompt) → dict`. The `LLMBackend` protocol is the only interface Stage 5b depends on — no provider details leak into extraction logic.

**Current implementation: `OllamaBackend`**
- Calls Ollama `/api/generate` with `"format": "json"` (token-level JSON enforcement)
- Configurable via dataclass fields: `base_url`, `model`, `timeout`, `temperature`, `num_ctx`
- Default: `OllamaBackend()` → `http://localhost:11434`, model `qwen2.5:7b`

**Adding a new provider:** implement `complete(system_prompt, user_prompt) -> dict` — that is all Stage 5b requires.

**Design decisions recorded:**
- JSON mode differs per provider (Ollama `format:json`, OpenAI `response_format`, Anthropic: no native mode — use tool use). This is a real friction point when adding Anthropic.
- OpenAI-compatible format (Ollama `/v1`, OpenRouter, Groq, Together) makes one shared `OpenAICompatibleBackend` practical for most non-Anthropic providers — defer until needed.
- Do not implement backends for providers not yet in use. Define the interface now; add implementations on demand.

## Test Fixtures

Fixtures live in `data/PDF/` (git-ignored). Full details and feature coverage map in README.MD.

| File | Issuer | Bonds | Key features |
|------|--------|-------|-------------|
| `REPUBLIC OF ARGENTINA Form 424B5 Filed 2020-08-17.pdf` | Argentina (sovereign) | Multi | Amortizing, step-up, dual ISIN, SEC EDGAR |
| `Prospectus - 2021.pdf` | Province of Buenos Aires | 6 series | Amortizing, step-up coupon, dual currency USD+EUR, dual ISIN, LuxSE |
| `us_prospectus_and_prospectus_supplement.pdf` | Argentina (sovereign) | 4 types | GDP-linked, $81.8B 2005 restructuring |
| `PDVSA_XS0294364103.pdf` | PDVSA (Venezuela) | 3 series | Guaranteed, LuxSE, no BDT GoverningLaw match |
| `USG38327AB13_OC_EN_2.PDF` | GeoPark (Bermuda) | 1 (tap) | **Simplest fixture** — single bond, fixed rate bullet, New York law |
| `USL21779AD28_OC_EN_3.pdf` | CSN Resources (Luxembourg/Brazil) | 2 series | Guaranteed, tap, multi-bond |
| `USP3710FAU86_OC_EN.PDF` | EDENOR (Argentina utility) | 1 | Amortizing 3 installments, dual ISIN |
| `USP98047AC08_PR_EN.pdf` | Volcan (Peru mining) | 1 | Listing memorandum format, guaranteed |
| `XS2278474924_OC_EN_2.pdf` | Liquid Telecom (England/Africa) | 1 | Senior secured, English law, 622 pages |

**Start with:** `USG38327AB13_OC_EN_2.PDF` (GeoPark) — single bond, no amortization, 191 pages.

When adding a new fixture: add a row above + a row to the README fixture table, add a pytest parametrize entry.

## Phase 2 — API Contract (async REST, deferred)

```
POST /jobs         → { job_id: "..." } per file
GET  /jobs/{id}    → { status: "queued"|"processing"|"done_valid"|"done_partial"|"failed" }
GET  /jobs/{id}/result  → BDT XML or ZIP download
GET  /jobs/{id}/log     → extraction trace
DELETE /jobs/{id}  → cancel/cleanup
```

MVP queue: file-based (watched directory). Future: Redis.

## Development Environment

**Virtual environment:** `.venv/` (Python 3.11, created via `python3.11 -m venv .venv`). Activate with `source .venv/bin/activate` or invoke directly via `.venv/bin/python`.

**Install dependencies:** `.venv/bin/pip install -r requirements.txt`

**Run tests:** `.venv/bin/python -m pytest tests/ -v`

**Run linter:** `.venv/bin/ruff check --fix . && .venv/bin/ruff format .`

## Key Directories & Files

- `.docs/ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02/` — BDT XSD, example XMLs, user guide
- `.docs/amortization_standard.MD` — email to ICMA explaining FpML + ACTUS approach
- `data/PDF/` — PDF test fixtures (git-ignored)
- `data/output/` — output XMLs and ZIPs (git-ignored)
- `data/output/debug/` — intermediate stage outputs written by `tests/test_stage_outputs.py` (git-ignored)
- `pipeline/llm_backend.py` — `LLMBackend` protocol + `OllamaBackend` implementation
- `data/jobs/` — file-based job queue (git-ignored, Phase 2 only)
- `docker-compose.yml` — stub, ready for API/worker/LLM services
- `.github/workflows/test.yml` — CI stub, tests added per service

## Coding Standards

**Python version:** 3.11+

**Type hints:** Required on all public functions and dataclass fields. Use `from __future__ import annotations` at top of every module for modern `X | Y` syntax.

**Formatter/linter:** `ruff` (replaces black + isort + flake8 in one tool).
- Line length: 99
- Target: `py311`
- Rules: `E`, `F`, `W`, `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM` (simplify)
- Format: ruff format (black-compatible)
- Run: `ruff check --fix . && ruff format .`

**Docstrings:** Google-style. Required for modules and public functions. Private helpers only need docstrings when logic is non-obvious.

**Naming:**
- `snake_case` for functions, variables, module files
- `PascalCase` for classes and dataclasses
- `UPPER_SNAKE` for module-level constants
- Pipeline modules: `stage{N}_{name}.py` (e.g., `stage5a_anchor.py`)
- Test modules: `test_stage{N}_{name}.py`

**Imports order** (enforced by ruff `I`): stdlib, blank line, third-party, blank line, local. `from __future__ import annotations` always first.

**Error handling:** Raise specific exceptions (`FileNotFoundError`, `ValueError`, `RuntimeError`). Never bare `except:`. Define `pipeline/errors.py` for custom pipeline exceptions if needed.

**Data structures:** Use `@dataclass` for stage inputs/outputs. Keep dataclasses immutable where possible (`frozen=True` for value objects).

## Testing Standards

**Framework:** pytest (already in requirements)

**Organization:**
- One test file per pipeline module: `test_stage2_parse.py`, `test_stage3_find.py`, etc.
- Class-based grouping: `TestParse{Fixture}`, `TestFind{Fixture}`, etc.
- `conftest.py` for shared fixtures and skip markers

**Fixtures (pytest):**
- Session-scoped for expensive operations (PDF parsing, section finding)
- Function-scoped for cheap/isolated operations
- Module-level `_doc_cache` dict for parametrized cross-fixture tests

**Skip markers for external dependencies:**
- `requires_pdf` — skip if PDF fixtures not present (git-ignored, CI-safe)
- `requires_ollama` — skip if Ollama not running at localhost:11434
- `requires_network` — skip if external APIs (GLEIF) unreachable

**Parametrize:** Use `@pytest.mark.parametrize` with `pytest.param(..., id="name")` for readability.

**Naming:** `test_{what}_{scenario}` for methods, `Test{Feature}` for classes.

**Assertions:** One logical assertion per test. Use descriptive messages on non-obvious assertions: `assert len(sections) >= 1, "GeoPark should have at least one bond section"`.

**Coverage:** `pytest-cov` with target 90%+ on deterministic code (stages 2-4, 5a, 5c, 6). LLM integration tests (5b) are optional/skipped in CI.

**Running tests:**
- All tests: `pytest tests/ -v`
- Skip external deps: `pytest tests/ -v -m "not requires_ollama and not requires_network"`
- Single stage: `pytest tests/test_stage2_parse.py -v`

## Future Steps (deferred from MVP)

1. OCR support for scanned PDFs (`docling` / `easyocr`)
2. Redis job queue (Phase 2)
3. ACTUS integration for amortization schedule validation
4. Step-up coupon extraction — `StepCouponSchedule` extension (3 of 9 fixtures require it)
5. Floating rate bond support
6. Confidence scoring per extracted field
7. Gradio UI front-end
8. ICMA enum extension proposals (more business day centers, governing laws, clearing systems)
