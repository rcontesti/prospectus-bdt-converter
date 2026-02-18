# Prospectus BDT Converter

A pipeline that transforms bond prospectuses and indentures (PDF) into structured XML conforming to the **ICMA Bond Data Taxonomy (BDT) v1.2**, with custom extensions for amortizing instruments. The system runs as a **Docker API service** that accepts batches of PDFs and returns batches of BDT XMLs.

---

## Table of Contents

- [Context](#context)
- [Objective](#objective)
- [Pipeline Stages](#pipeline-stages)
- [BDT Schema Reference](#bdt-schema-reference)
- [Known BDT Gaps and Workarounds](#known-bdt-gaps-and-workarounds)
- [Amortization Extension](#amortization-extension)
- [API Design](#api-design)
- [Technology Stack](#technology-stack)
- [Test Fixtures](#test-fixtures)
- [Future Steps](#future-steps)
- [Resources](#resources)

---

## Context

Debt capital markets are rapidly digitalizing. To counter fragmentation across systems, the **Bond Data Taxonomy (BDT)** was introduced by ICMA in 2023. It provides a shared, machine-readable vocabulary for the essential terms of a bond — financial terms (principal, currency, coupon, maturity), key dates (pricing, settlement), and contextual information (governing law, parties, ratings, selling restrictions). It is expressed as XML/XSD and leverages ISO standards throughout.

**The three complementary standards for bond tokenization:**

| Standard | Answers | Scope |
|----------|---------|-------|
| BDT | "What is this bond?" | Static terms, from the prospectus |
| CDM | "What happened to it?" | Events, lifecycle |
| CMTAT | "How is it represented on-chain?" | Token logic + compliance |

---

## Objective

Given a PDF of a bond prospectus or indenture, produce a BDT-compliant XML file capturing the bond's key economic and legal terms.

**Inputs:** PDF files from any source — SEC EDGAR (424B5, 424B3), Luxembourg Stock Exchange, Singapore Stock Exchange, or any other exchange.

**Outputs:** BDT v1.2 XML files, extended with custom amortization schedule elements where applicable.

**Core constraints:**
- Open-source tools only throughout the pipeline
- Small, locally-runnable LLMs only — model-agnostic design, no proprietary API calls
- Self-contained Docker deployment

---

## Pipeline Stages

The conversion has **six sequential stages**. Each stage is separately containerizable.

### Stage 1 — PDF Ingestion (API + Job Queue)

The API accepts batches of PDF files. Each submission gets a `job_id`. Jobs queue for async processing. Clients poll for status and download results when ready.

**MVP simplification:** file-based queue (watched directory). Redis can be added later.

### Stage 2 — PDF Parsing

Convert the PDF into structured text preserving logical layout (headings, tables, paragraphs). Bond prospectuses often exceed 400 pages and include dense legal tables; some may be image-based scans.

**Approach:** Open-source document library (candidate: `docling` or `pymupdf`). Output: structured JSON with page numbers and element types (heading, paragraph, table, etc.).

### Stage 3 — Document Segmentation

Split the parsed document into named sections using the Table of Contents.

**Approach:**
1. Locate the TOC (heuristic: first occurrence of a recurring list of titled references within the first ~15% of the document).
2. Extract section titles and page/offset references from the TOC.
3. Split full document text into labelled sections.

No LLM required for this stage.

### Stage 4 — Target Section Identification

Identify **all sections** in the document that describe bond terms. A prospectus may contain more than one bond (e.g. a base prospectus covering multiple series, or an exchange offer with several new bonds). Each bond produces a separate BDT output.

Common section titles to match:

- *"Description of the Notes"*
- *"Description of the Bonds"*
- *"Terms and Conditions of the Notes"*
- *"Terms and Conditions"*
- *"Description of the Securities"*

**Approach:** Fuzzy string match against all TOC section titles — return every match, not just the first. If no confident match, use the LLM to classify each section by content.

**Output:** An ordered list of `(section_title, page_start, page_end)` tuples, one per bond found.

### Stage 5 — BDT Field Extraction

Run extraction once per bond section identified in Stage 4. Each run produces one BDT XML. Bonds are primarily identified by their **ISIN** — this is the key that links all extracted fields to a specific instrument.

**Strategy:** Extract fields in thematic groups (not all at once) to stay within context windows:

| Group | Fields |
|-------|--------|
| Identifiers | ISIN, CUSIP, Common Code, SEDOL |
| Amounts & currency | AggregateNominalAmount, SpecifiedDenomination, IntegralMultiples, SpecifiedCurrency |
| Dates | PricingDate, IssueDate, SettlementDate, MaturityDate, InterestCommencementDate |
| Interest | InterestType, InterestRate, InterestPaymentFrequency, DayCountFraction, BusinessDayConvention |
| Parties | Issuer, lead managers, trustee, paying agent, fiscal agent (name + LEI lookup) |
| Issuance terms | IssuanceType, IssuePrice, FormOfNote, StatusOfNote, GoverningLaw |
| Restrictions | SellingRestrictions, PRIIPsRestriction, ManufacturerTargetMarket |
| Amortization | AmortizationSchedule steps (if amortizing) |

Each group is validated against BDT enum constraints and ISO formats before assembly.

**LLM:** Model-agnostic — Ollama or HuggingFace TGI. Minimum 32K context window. Target models: smollm3, Qwen2.5, Phi-3.5-mini, Mistral 7B.

### Stage 6 — XML Generation + Validation

Assemble extracted fields into a BDT v1.2 XML document per bond. If extensions are applied (e.g. amortization schedule), append an `<ExtensionManifest>` block and the extension data (see [Amortization Extension](#amortization-extension)). Validate the BDT core against the XSD before returning.

**Multi-bond output:** When a PDF yields N bonds, the job result is a ZIP containing N XML files, named by ISIN (e.g. `XS2524143554.xml`).

The XSD files are in `.docs/ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02/`.

---

## BDT Schema Reference

**Version:** BDT Pack 1.2 (2 February 2024), published by ICMA.
**Namespace:** `urn:icma:xsd:ICMABondDataTaxonomy`
**Schema files:** `icma-bond-data-taxonomy.xsd`, `icma-bond-data-taxonomy-enums.xsd`, `icma-bond-data-taxonomy-isotypes.xsd`

### Document Structure

```
Document
└── ICMABondDataTaxonomy
    ├── PartyRole (1..*)     — links role type to a Party by ID
    ├── Party (1..*)         — name, LEI, ratings
    ├── Issuance (0..1)      — issuance-level terms
    └── Product (0..1)       — product/security-level terms
```

### Required Fields (minOccurs=1)

**PartyRole:** `PartyRoleType`, `PartyID`

**Party:** `PartyName`, `LEIIdentifier`

**Issuance:**
- `IssuanceType` (PROGRAMME | STANDALONE)
- `SpecifiedDenomination`, `SpecifiedCurrency`
- `PricingDate`, `IssueDate`, `SettlementDate`
- `IssuePrice`
- `Listing` (1+)
- `GoverningLaw`
- `SellingRestrictions`
- `ManufacturerTargetMarket` (1+)

**Product:**
- `FormOfNote`
- `StatusOfNote`
- `AggregateNominalAmount`
- `MaturityDate`
- `InterestPayment` → requires: `InterestType`, `InterestCommencementDate`, `InterestPayments`
- `InterestPayments` → requires: `InterestPaymentFrequency`, `PayableDate` (1..4), `FirstPayment`
- `DayCountFraction`
- `BusinessDayConvention`
- `BusinessDayCenter`

### Key Enumerations

**PartyRoleType:** `ISSUER`, `GUARANTOR`, `LEAD_MANAGER`, `JOINT_LEAD_MANAGER`, `ARRANGER`, `FISCAL_AGENT`, `PRINCIPAL_PAYING_AGENT`, `CALCULATION_AGENT`, `STABILISATION_MANAGER`, `TRUSTEE`, `REGISTRAR`, `CUSTODIAN`, `PAYING_AGENT`, `TRANSFER_AGENT`, `ISSUE_AGENT`, `LEGAL_ADVISOR`, `LODGING_AGENT`, `CENTRAL_ACCOUNT_KEEPER`, `TOKENISATION_MANAGER`, `CRYPTO_SECURITIES_REGISTRAR`, `JOINT_GLOBAL_COORDINATOR`, `JOINT_BOOKRUNNER`, `MARKET_PRACTICE_ADVISOR`, `DIRECT_PARTICIPANT`, `DEPOSIT_BANK`, `CASH_TOKEN_MANAGER`, `PLATFORM_OPERATOR`, `OTHER_PARTYROLE_TYPE`

**IssuanceType:** `PROGRAMME` | `STANDALONE`

**StatusOfNote:** `SENIOR_SECURED` | `SENIOR_UNSECURED` | `SENIOR_PREFERRED` | `SENIOR_NON_PREFERRED` | `SUBORDINATED`

**FormOfNote:** `BEARER` | `REGISTERED` | `DEMATERIALISED` | `BOOK_ENTRY` | `FED_BOOK_ENTRY` | `MATERIALISED_BEARER` | `MATERIALISED_REGISTERED` | `DEMATERIALISED_BEARER` | `DEMATERIALISED_BOOK_ENTRY` | `DEMATERIALISED_REGISTERED` | `UNCERTIFICATED_DEMATERIALISED_BOOK_ENTRY` | `UNCERTIFICATED_REGISTERED` | `UNCERTIFIED` | `UNCERTIFIED_DEMATERIALISED_BOOK_ENTRY` | `COLLECTIVE_DEBT_REGISTERED_CLAIM`

**InterestType:** `FIXED` | `FLOATING` | `ZERO_COUPON` | `INDEX_LINKED_INTEREST`

**InterestPaymentFrequency:** `ANNUALLY` | `SEMIANNUALLY` | `QUARTERLY` | `NONE`

**DayCountFraction:** `ICMA_ACT/ACT` | `ISDA_ACT/ACT` | `30/360` | `30/365` | `ACT/360` | `ACT/365`

**BusinessDayConvention:** `FOLLOWING_UNADJUSTED` | `PRECEDING` | `MODIFIED_FOLLOWING_ADJUSTED`

**BusinessDayCenter:** `TARGET` | `TARGET2` | `FRANKFURT` | `NEW_YORK` | `LUXEMBOURG`

**GoverningLaw:** `AUSTRIAN_LAW` | `BELGIAN_LAW` | `CANADIAN_LAW` | `DANISH_LAW` | `DUTCH_LAW` | `ENGLISH_LAW` | `FINISH_LAW` | `FRENCH_LAW` | `GERMAN_LAW` | `ITALIAN_LAW` | `LUXEMBOURG_LAW` | `NEW_SOUTH_WALES_LAW` | `NEW_YORK_LAW` | `ONTARIO_LAW` | `SPANISH_LAW`

**SellingRestrictionCode:** `REGS_CAT1` | `REGS_CAT2` | `REGS_CAT3` | `144A` | `TEFRA_C` | `TEFRA_D` | `TEFRA_NA` | `SEC_REG` | `NOT_APPLICABLE`

**ListingMarket:** includes `LUXEMBOURG_STOCK_EXCHANGE`, `SINGAPORE_SGX`, `LONDON_STOCK_EXCHANGE`, `NEW_YORK_STOCK_EXCHANGE` (not present — only the exchanges listed in the enum), `NOT_LISTED`, and ~35 others

**ClearingSettlementSystem:** `CLEARSTREAM_BANKING_FRANKFURT` | `DTCC` | `EUROCLEAR_BANK_SA/NV` | `CLEARSTREAM_BANKING_S.A.` | `CENTRAL_MONEY_MARKETS_UNIT`

**RedemptionPaymentBasisType:** `PAR` | `PARTLY_PAID` | `INDEX_LINKED_INTEREST` | `INSTALLMENT` | `DUAL_CURRENCY`

**RatingAgency:** `FITCH` | `MOODYS` | `SP` | `DBRS`

**RatingOutlook:** `POSITIVE` | `STABLE` | `NEGATIVE` | `DEVELOPING` | `NOT_MEANINGFULL` | `EVOLVING` | `NOT_APPLICABLE`

---

## Bond Identity and ISIN Handling

### ISIN as primary identifier

Each bond in a prospectus is identified by its **ISIN** (ISO 6166). The ISIN is the primary key used to name output files, cross-reference related bonds, and deduplicate extraction runs. If a bond section contains no ISIN, a temporary identifier is generated and flagged for human review.

### Dual-ISIN bonds (same economic bond, two markets)

A single bond is often marketed in two regulatory tranches with different ISINs:

| Tranche | ISIN prefix | Market | Clearing | Selling restriction |
|---------|-------------|--------|----------|---------------------|
| Rule 144A | `US...` | US QIBs | DTCC | `144A` |
| Regulation S | `XS...` or `AR...` | Non-US | Euroclear / Clearstream | `REGS_CAT2` |

These share the same economic terms (coupon, maturity, governing law) and are often fungible after a lock-up period. They are **one economic bond**, not two.

**Design decision:** produce **one BDT XML per economic bond**. Both ISINs are recorded in `<SecurityIdentifierList>`, both clearing systems in `<ClearingSettlementSystem>`, and both selling restrictions in `<SellingRestrictions>`. The output file is named after the Reg S ISIN for internationally-marketed bonds, or the 144A ISIN for US-domestic bonds.

When the two tranches have materially different terms (different principal amounts, different maturity dates), they must be treated as separate bonds and produce separate BDT XMLs.

### Multi-bond prospectuses

A prospectus may describe multiple distinct bonds. Common cases:
- Exchange offer: old bonds exchanged for several new series with different maturities/coupons
- Base prospectus: describes a family of instruments under one programme

Each distinct bond (unique economic terms + unique ISIN set) produces one BDT XML. The job result is a ZIP when N > 1.

---

## Known BDT Gaps and Workarounds

These are limitations discovered from reading the actual XSD that affect real-world bonds:

| Gap | Impact | Our Workaround |
|-----|--------|----------------|
| No amortization schedule | Cannot represent stepwise principal repayments | Custom `<AmortizationSchedule>` extension (FpML-inspired) |
| `BusinessDayCenter` only 5 options (TARGET, TARGET2, FRANKFURT, NEW_YORK, LUXEMBOURG) | Cannot represent Buenos Aires, Tokyo, etc. | Use `NEW_YORK` for USD bonds; document actual center in `<AdditionalSellingRestrictions>` or custom element |
| `GoverningLaw` only 15 options (no Argentinian law, no Singapore law, etc.) | Argentina bonds under Argentine law cannot be represented | Fall back to `NEW_YORK_LAW` for the international tranche; flag domestic-law tranche separately |
| `ClearingSettlementSystem` has no Caja de Valores (Argentina) or CDP (Singapore) | Local clearing systems unrepresentable | Use `DTCC` for 144A tranche; document local system in free text |
| `RedemptionPaymentBasisType` has `INSTALLMENT` but no schedule fields | Signals amortizing intent but carries no data | Use our `<AmortizationSchedule>` extension |
| `ListingMarket` is a closed enum | Not all exchanges are listed (e.g. NYSE is absent) | Use `NOT_LISTED` and document actual exchange in a custom element |
| `RatingAgency` only 4 values (Fitch, Moodys, S&P, DBRS) | No support for local rating agencies | Use `OTHER_PARTYROLE_TYPE` pattern; document in free text |

---

## Extension Framework

BDT v1.2 covers vanilla bonds well but leaves gaps for real-world structures. This project fills those gaps through a **versioned extension framework**. Extensions are designed to be separable from — and invisible to — the core BDT namespace, so the BDT core XML remains valid against the ICMA XSD.

### Extension conventions

- **Namespace pattern:** `urn:bdt-ext:{name}:v{major}` (e.g. `urn:bdt-ext:amortization:v1`)
- **Versioning:** each extension is versioned independently using semantic versioning. A major version bump indicates a breaking schema change.
- **Declaration:** every output XML that uses extensions includes an `<ExtensionManifest>` block immediately after `</ICMABondDataTaxonomy>`, listing each extension applied:

```xml
<ExtensionManifest xmlns="urn:bdt-ext:manifest:v1">
  <Extension name="amortization" version="1.0" namespace="urn:bdt-ext:amortization:v1"/>
  <!-- future extensions listed here -->
</ExtensionManifest>
```

- **Placement:** extension data lives inside the relevant BDT element using its own namespace, so standard XML parsers can ignore it cleanly.

### Amortization extension (v1.0)

BDT v1.2 has `RedemptionPaymentBasisType = INSTALLMENT` to flag an amortizing instrument, but no mechanism to carry the schedule. This extension adds an `<AmortizationSchedule>` block inside `<Product>`, modelled on **FpML's `notionalStepSchedule`** element (ISDA).

Each `<step>` records the **outstanding notional after** the principal payment on that date:

```xml
<Product>
  <!-- ... standard BDT fields ... -->
  <RedemptionPaymentBasis>INSTALLMENT</RedemptionPaymentBasis>

  <!-- Amortization extension v1.0 -->
  <AmortizationSchedule xmlns="urn:bdt-ext:amortization:v1">
    <step>
      <stepDate>2026-08-21</stepDate>
      <stepValue currency="USD">1000000</stepValue>
    </step>
    <step>
      <stepDate>2027-08-21</stepDate>
      <stepValue currency="USD">500000</stepValue>
    </step>
    <step>
      <stepDate>2028-08-21</stepDate>
      <stepValue currency="USD">0</stepValue>
    </step>
  </AmortizationSchedule>
</Product>
```

**Design rationale:**
- The FpML `notionalStepSchedule` is an established industry pattern for time-varying notionals — descriptive, not computational.
- **ACTUS** (actusfrf.org) provides an algorithmic complement: given contract terms, ACTUS derives the full cash flow schedule deterministically. Reserved for future schedule validation or generation.

### Future extensions (placeholder)

New extensions are added here as they are designed. Each must follow the namespace/versioning convention above and document its schema alongside the implementation. Candidates:
- Floating rate reset schedule
- Step-up / step-down coupon schedule
- Linked bond cross-reference (for exchangeable / convertible bonds)

---

## API Design

The service exposes an **asynchronous REST API** designed for batch processing of large documents.

Bond prospectuses exceed 400 pages. PDF parsing + LLM inference can take minutes per document. Synchronous HTTP would timeout and prevent retries. An async model lets clients submit and disconnect, the LLM worker scale independently, and jobs be retried on failure.

### Endpoints (planned)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/jobs` | Submit batch of PDFs; returns `job_id` per file |
| `GET` | `/jobs/{job_id}` | Poll status: `queued` → `processing` → `done` / `failed` |
| `GET` | `/jobs/{job_id}/result` | Download BDT XML for a completed job |
| `GET` | `/jobs/{job_id}/log` | Download processing log / extraction trace |
| `DELETE` | `/jobs/{job_id}` | Cancel or clean up a job |

### Docker service topology

```
┌─────────────────────┐
│   API service       │  FastAPI — REST endpoints, job management
└────────┬────────────┘
         │ enqueues jobs
┌────────▼────────────┐
│   Job queue         │  MVP: file-based (watched dir). Future: Redis
└────────┬────────────┘
         │ dequeues jobs
┌────────▼────────────┐
│   Worker service    │  Runs pipeline Stages 2–6
│   ┌──────────────┐  │
│   │  LLM runner  │  │  Ollama or HuggingFace TGI (swappable)
│   └──────────────┘  │
└─────────────────────┘
```

Input PDFs and output XMLs are persisted to a shared Docker volume.

---

## Technology Stack

| Component | MVP choice | Future option |
|-----------|-----------|---------------|
| PDF parsing | `pymupdf` (fast, reliable) | `docling` (layout-aware, OCR) |
| Document segmentation | Regex + heuristics | — |
| Section identification | Fuzzy string match | LLM classifier fallback |
| Field extraction | Small LLM via Ollama | HuggingFace TGI |
| LLM model | Qwen2.5-7B or Phi-3.5-mini | smollm3, Mistral 7B |
| XML generation | Python `lxml` | — |
| XSD validation | `lxml` against BDT XSD | — |
| API framework | FastAPI | — |
| Job queue | File-based (watched dir) | Redis |
| Container | Docker + Docker Compose | Kubernetes |
| Testing | pytest + Argentina 2020 PDF | Full regression suite |
| CI/CD | GitHub Actions | — |

---

## Test Fixtures

Test fixtures are real prospectus PDFs stored in `data/PDF/` (git-ignored). Each fixture is tagged with the bond features it exercises, to make it clear which test to run when working on a specific stage or extension.

### Current fixtures

| File | Issuer | Features tested |
|------|--------|----------------|
| `REPUBLIC OF ARGENTINA Form 424B5 Filed 2020-08-17.pdf` | Argentina (sovereign) | Amortizing, dual ISIN (144A + Reg S), multi-bond (multiple new series), New York law, DTCC, STANDALONE |
| `Prospectus - 2021.pdf` | TBD | TBD |
| `us_prospectus_and_prospectus_supplement.pdf` | TBD | TBD |

### Primary fixture: Argentina 2020 restructuring

**Why this document:** The Argentina 2020 sovereign bond restructuring is an unusually rich test case:
- **Amortizing** — principal repaid in tranches: exercises the amortization extension
- **Multi-bond** — the exchange offer produced several new bond series with different maturities/coupons: exercises Stage 4's multi-section detection
- **Dual ISIN per bond** — each series has a 144A ISIN (DTCC) and a Reg S ISIN (Euroclear/Clearstream): exercises the dual-ISIN identity logic
- **New York law** — maps to `NEW_YORK_LAW` in BDT ✓
- **STANDALONE** issuance — simpler than a programme for MVP
- Target section: "Description of the New Securities" or "Terms and Conditions of the New Securities"

### Adding new fixtures

When adding a new PDF for testing:
1. Place it in `data/PDF/` (git-ignored)
2. Add a row to the table above with issuer and feature tags
3. Add a pytest parametrize entry in the relevant test file
4. Prefer documents that exercise features not already covered (vanilla fixed-rate, floating-rate, programme issuance, non-English governing law, etc.)

---

## Future Steps

Items deferred from MVP, in rough priority order:

1. **OCR support** — some PDF prospectuses are scans; requires `docling` or `easyocr` in the parsing stage
2. **Redis job queue** — replace file-based queue for production robustness and horizontal scaling
3. **ACTUS integration** — use the ACTUS standard to algorithmically validate or derive the amortization schedule from contract terms
4. **Multi-series prospectuses** — a single PDF may describe multiple bonds (series/tranches); Stage 4 must return multiple target sections and Stage 5 must extract one BDT per series
5. **LEI lookup** — after extracting party names, call the GLEIF API to resolve LEIs automatically rather than relying on the LLM
6. **BDT enum extension proposals** — engage ICMA to propose additions: more business day centers (Buenos Aires, Singapore, Tokyo), more governing laws (Argentinian, Singapore), more clearing systems (Caja de Valores, CDP)
7. **Floating rate bond support** — BDT has `FloatingRatePayment` in the schema but field extraction for floating rate terms requires different prompt groups
8. **Confidence scoring** — each extracted field should carry a confidence score; low-confidence fields flagged for human review
9. **Diff / update mode** — given an existing BDT XML and a new PDF, emit only the changed fields
10. **UI / Gradio front-end** — simple interface for uploading PDFs and downloading XMLs (Gradio already in venv)

---

## Resources

- [ICMA Bond Data Taxonomy](https://www.icmagroup.org/fintech-and-digitalisation/fintech-advisory-committee-and-related-groups/bond-data-taxonomy/) — BDT Pack v1.2 download (XSD, user guide, XML examples)
- [FpML `notionalStepSchedule`](https://schemas.liquid-technologies.com/FpML/5.9/confirmation/notionalstepschedule.html) — reference for amortization extension pattern
- [ACTUS Standard](https://www.actusfrf.org/) — algorithmic contract type standard
- `.docs/ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02/` — local copy of BDT Pack (XSD files, example XMLs, user guide)
- `.docs/amortization_standard.MD` — rationale for FpML + ACTUS approach for amortizing bonds
