# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A pipeline that converts bond prospectus / indenture PDFs into **ICMA BDT v1.2 XML** files. Runs as a Docker async API service (batch PDFs in → batch XMLs out).

**Hard constraints:** open-source only, model-agnostic locally-runnable LLM, self-contained Docker.

## Pipeline (6 stages)

| Stage | Name | LLM | Status |
|-------|------|-----|--------|
| 1 | API + file-based job queue (FastAPI) | No | Not started |
| 2 | PDF parsing → structured JSON (pymupdf MVP, docling future) | No | Not started |
| 3 | TOC extraction + document segmentation | No | Not started |
| 4 | Target section ID ("Description of the Notes" etc.) | Fallback | Not started |
| 5 | BDT field extraction — grouped prompts | Yes | Not started |
| 6 | XML assembly + XSD validation (lxml) | No | Not started |

**Stage 4:** return ALL matching sections, not just the first — a prospectus may describe multiple bonds. Output: list of `(section_title, page_start, page_end)` per bond. Section titles to match (fuzzy): "Description of the Notes", "Description of the Bonds", "Terms and Conditions of the Notes", "Terms and Conditions", "Description of the Securities"

**Stage 5:** run once per bond section from Stage 4. ISIN is the primary bond identifier — output files are named `{ISIN}.xml`. If no ISIN is found, generate a temp ID and flag for review.

**Stage 6:** one BDT XML per bond. If N > 1 bonds found in a PDF, job result is a ZIP of N XMLs.

**Stage 5 extraction groups** (each sent as a separate LLM prompt with structured JSON output schema):
- Identifiers: ISIN, CUSIP, Common Code, SEDOL
- Amounts: AggregateNominalAmount, SpecifiedDenomination, IntegralMultiples, SpecifiedCurrency
- Dates: PricingDate, IssueDate, SettlementDate, MaturityDate, InterestCommencementDate
- Interest: InterestType, InterestRate, InterestPaymentFrequency, DayCountFraction, BusinessDayConvention, BusinessDayCenter
- Parties: Issuer, lead managers, trustee, paying agent, fiscal agent (name + LEI; LEI to be looked up via GLEIF in future)
- Issuance: IssuanceType, IssuePrice, FormOfNote, StatusOfNote, GoverningLaw
- Restrictions: SellingRestrictions, PRIIPsRestriction, ManufacturerTargetMarket
- Amortization: stepDate + stepValue pairs (if amortizing — check RedemptionPaymentBasis)

## BDT Schema — Critical Constraints for Extraction

XSD files: `.docs/ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02/`

**Namespace:** `urn:icma:xsd:ICMABondDataTaxonomy`

**Required fields that MUST be present for a valid document:**
- Issuance: `IssuanceType`, `SpecifiedDenomination`, `SpecifiedCurrency`, `PricingDate`, `IssueDate`, `SettlementDate`, `IssuePrice`, `Listing` (1+), `GoverningLaw`, `SellingRestrictions`, `ManufacturerTargetMarket` (1+)
- Product: `FormOfNote`, `StatusOfNote`, `AggregateNominalAmount`, `MaturityDate`, `InterestPayment`, `DayCountFraction`, `BusinessDayConvention`, `BusinessDayCenter`
- InterestPayment requires: `InterestType`, `InterestCommencementDate`, `InterestPayments`
- InterestPayments requires: `InterestPaymentFrequency`, `PayableDate` (1..4 with Day+Month), `FirstPayment` (with PaymentDate)

**Enum constraints the LLM must output exactly** (these are strictly validated by XSD):
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
| No amortization schedule | Use `RedemptionPaymentBasis=INSTALLMENT` + custom `<AmortizationSchedule>` extension |
| `BusinessDayCenter` missing Buenos Aires, Tokyo, etc. | Use `NEW_YORK` for USD bonds |
| `GoverningLaw` missing Argentinian, Singapore law | Use `NEW_YORK_LAW` for international tranche |
| `ClearingSettlementSystem` missing Caja de Valores, CDP | Use `DTCC` for 144A tranche |
| `RatingAgency` only 4 values | Free text for others |

## Extension Framework

Extensions use versioned namespaces: `urn:bdt-ext:{name}:v{major}`. Every XML that uses extensions declares them in an `<ExtensionManifest xmlns="urn:bdt-ext:manifest:v1">` block immediately after `</ICMABondDataTaxonomy>`. Extensions live inside standard BDT elements using their own namespace — the core BDT remains XSD-valid.

**Amortization extension v1.0** (`urn:bdt-ext:amortization:v1`): when `RedemptionPaymentBasisType = INSTALLMENT`, append inside `<Product>`. Each `<step>` = outstanding notional *after* payment on `stepDate`:

```xml
<AmortizationSchedule xmlns="urn:bdt-ext:amortization:v1">
  <step><stepDate>2026-08-21</stepDate><stepValue currency="USD">1000000</stepValue></step>
  <step><stepDate>2027-08-21</stepDate><stepValue currency="USD">0</stepValue></step>
</AmortizationSchedule>
```

FpML `notionalStepSchedule` is the design reference. ACTUS is noted for future algorithmic schedule derivation. Future extension candidates: floating rate reset schedule, step-up coupon schedule, linked bond cross-reference.

## Dual-ISIN / Multi-Bond Logic

**Dual-ISIN (same economic bond, two markets):** a 144A ISIN + Reg S ISIN represent one bond. Produce **one BDT XML** with both ISINs in `<SecurityIdentifierList>`, both clearing systems in `<ClearingSettlementSystem>`, both selling restrictions in `<SellingRestrictions>`. File named after Reg S ISIN for international bonds. If tranches have materially different terms (different amounts, different maturity), treat as separate bonds.

**Multi-bond prospectus:** Stage 4 returns N section tuples → Stage 5 runs N times → Stage 6 produces N XMLs → API result is a ZIP.

## Test Fixtures

Fixtures live in `data/PDF/` (git-ignored). Tag each with features it exercises.

| File | Features |
|------|----------|
| `REPUBLIC OF ARGENTINA Form 424B5 Filed 2020-08-17.pdf` | Amortizing, multi-bond, dual ISIN (144A + Reg S), New York law, DTCC, STANDALONE |
| `Prospectus - 2021.pdf` | TBD |
| `us_prospectus_and_prospectus_supplement.pdf` | TBD |

**Primary:** Argentina 2020 — amortizing sovereign bond restructuring with multiple new series, each having a 144A and Reg S ISIN. Target section: "Description of the New Securities" (or similar). Exercises: amortization extension, multi-bond detection, dual-ISIN logic, standard BDT fields.

When adding a new fixture: add a row above, add a pytest parametrize entry, prefer documents that cover uncovered features (vanilla fixed-rate, floating-rate, programme issuance).

## API Contract (async REST)

```
POST /jobs         → { job_id: "..." } per file
GET  /jobs/{id}    → { status: "queued"|"processing"|"done"|"failed" }
GET  /jobs/{id}/result  → BDT XML download
GET  /jobs/{id}/log     → extraction trace
DELETE /jobs/{id}  → cancel/cleanup
```

Job states: `queued` → `processing` → `done` / `failed`

MVP queue: file-based (watched directory). Future: Redis.

## Key Directories & Files

- `.docs/ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02/` — BDT XSD, example XMLs, user guide
- `.docs/amortization_standard.MD` — email to ICMA explaining FpML + ACTUS approach
- `data/PDF/` — PDF test fixtures (git-ignored)
- `data/output/` — output XMLs and ZIPs (git-ignored)
- `data/jobs/` — file-based job queue (git-ignored, MVP only)
- `docker-compose.yml` — stub, ready for API/worker/LLM services
- `.github/workflows/test.yml` — CI stub, tests added per service

## Future Steps (deferred from MVP)

1. OCR support for scanned PDFs (`docling` / `easyocr`)
2. Redis job queue
3. ACTUS integration for amortization schedule validation
4. Multi-series prospectus support (one PDF → multiple BDTs)
5. Automatic LEI resolution via GLEIF API
6. Confidence scoring per extracted field
7. Gradio UI front-end
8. ICMA enum extension proposals (more business day centers, governing laws, clearing systems)
