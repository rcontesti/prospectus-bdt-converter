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

## Build Order

The pipeline is built **CLI-first, API-last**. Stages 2–6 are developed and validated as a command-line tool before any API scaffolding is added. This eliminates unnecessary complexity during the hardest part of the work.

```
Phase 1 (MVP):  python convert.py <input.pdf> --output <dir>/
Phase 2:        FastAPI wrapper around the same pipeline
```

## Pipeline Stages

The conversion has **six sequential stages**.

### Stage 1 — API + Job Queue *(built last)*

The API accepts batches of PDF files. Each submission gets a `job_id`. Jobs queue for async processing. Clients poll for status and download results when ready.

**Deferred to Phase 2.** During Phase 1 the pipeline is invoked via CLI. The file-based queue (watched directory) and FastAPI wrapper are added once Stages 2–6 produce correct output.

### Stage 2 — PDF Parsing

Convert the PDF into structured text preserving logical layout (headings, paragraphs, tables). Bond prospectuses often exceed 400 pages and include dense legal tables.

**Approach:** `pymupdf` for MVP — fast, reliable on text-based PDFs, preserves enough table structure for LLM consumption. `docling` added later for layout-aware extraction and OCR on scanned documents.

**Output:** list of pages, each with raw text and detected element types (heading, paragraph, table row).

### Stage 3 — Section Finding

Locate the section(s) in the document that contain bond terms. A prospectus may describe multiple bonds.

**MVP approach — heading detection, not TOC parsing:**
1. Scan the extracted text for lines that are short, isolated, and match target patterns (case-insensitive fuzzy match).
2. Target headings: *"Description of the Notes"*, *"Description of the Bonds"*, *"Terms and Conditions of the Notes"*, *"Terms and Conditions"*, *"Description of the Securities"*, *"Description of the New Securities"*.
3. For each match, take all text from that heading to the next major heading. That is one bond section.
4. Return all matches — every matched section is a separate bond candidate.

**Why not TOC-based:** TOC page numbers use the document's internal pagination (often S-1, S-2…), not the PDF page index. This mismatch is a reliable source of off-by-N errors. Heading detection is simpler and more robust for MVP.

**TOC parsing** is added as a future improvement for edge cases where heading detection produces overlapping or ambiguous results.

**Output:** ordered list of `(section_title, text)` tuples, one per bond found.

### Stage 4 — Summary Table Detection

Within each bond section, locate the **compact terms summary** before sending anything to the LLM. Most prospectuses open the "Description of the Notes" section with a 1–3 page table titled "Key Terms", "Summary of Terms", "Terms and Conditions Summary", or similar. This table contains the majority of BDT fields in dense, structured form.

**Approach:** scan the section for a table-like block (lines with consistent structure, keywords like "Maturity Date", "Interest Rate", "ISIN", "Aggregate Principal Amount") within the first 15% of the section. Extract this block as the **primary LLM input**. Use the full section text only as fallback.

**Why this matters:** sending a compact 2-page table to the LLM is far more reliable than sending 40 pages of legal prose. The LLM makes fewer errors and the extraction cost drops significantly.

### Stage 5 — BDT Field Extraction

Run extraction once per bond section from Stage 3. Each run produces one set of BDT fields. Bonds are primarily identified by their **ISIN** — this is the key that links all extracted fields to a specific instrument.

The extraction has three sequential sub-steps:

#### 5a — Bond Anchor

Before extracting any BDT fields, identify which bond this section is about:

```json
{ "bond_name": "...", "isins": ["XS...", "US..."] }
```

The returned ISIN set is embedded in all subsequent prompts: *"Extract the following fields for the bond with ISIN XS2385150334. Ignore all other bonds or ISINs mentioned in the text."* This resolves the ambiguity of having many ISINs, dates, and amounts in the same document.

#### 5b — Grouped LLM extraction

Fields are extracted in thematic groups. Each group is a focused prompt with:
- The anchor ISIN(s)
- The summary table text (or full section as fallback)
- A strict JSON output schema with the allowed enum values listed inline, so the LLM maps text → enum in context
- JSON mode enforced (Ollama `format: json`)

| Group | Fields | Notes |
|-------|--------|-------|
| Identifiers | ISIN, CUSIP, Common Code, SEDOL | First group — output used as anchor for all others |
| Amounts | AggregateNominalAmount, SpecifiedDenomination, IntegralMultiples, SpecifiedCurrency | |
| Dates | PricingDate, IssueDate, SettlementDate, MaturityDate, InterestCommencementDate | |
| Interest | InterestType, InterestRate, InterestPaymentFrequency, DayCountFraction, BusinessDayConvention, BusinessDayCenter | Enum values listed in prompt |
| Issuance terms | IssuanceType, IssuePrice, FormOfNote, StatusOfNote, GoverningLaw | Enum values listed in prompt |
| Parties | Issuer name, lead manager names, trustee, paying agent, fiscal agent | Names only — LEI resolved separately in 5c |
| Selling restrictions | SellingRestrictions, PRIIPsRestriction | Enum values listed in prompt |
| Amortization | stepDate + stepValue pairs | Only if bond is amortizing — detected from summary table |

`ManufacturerTargetMarket` is **not sent to the LLM**. It is set by rule in 5c.

#### 5c — Deterministic post-processing

After LLM extraction, a deterministic layer normalizes and validates — no interpretation:

| Input | Action |
|-------|--------|
| Date strings ("January 9, 2030") | Parse with `dateutil` → ISO 8601 (`2030-01-09`) |
| Amount strings ("US$500,000,000") | Strip symbols, parse float → `500000000.0` |
| ISIN strings | Validate 12-char format + ISO 6166 checksum |
| Enum value not in allowed list | Null + flag for review |
| Party names | Send to GLEIF API → resolve LEI. On miss: placeholder + flag |
| `ManufacturerTargetMarket` | Rule: if SellingRestrictions contains `144A` or `REGS_CAT2` but no EU/UK MiFID entry → `NOT_APPLICABLE`. Otherwise determine from context. |
| Any required field = null | Mark bond as `done_partial` (see Stage 6) |

**LLM:** Model-agnostic — Ollama with JSON mode enforced. Minimum 32K context window. Target models: Qwen2.5-7B, Phi-3.5-mini, Mistral 7B.

### Stage 6 — XML Assembly + Validation

Assemble extracted fields into the output document. Validate the BDT core against the XSD.

**Output document structure** (custom root wrapper to accommodate extensions alongside valid BDT):

```xml
<BDTDocument xmlns:bdt="urn:icma:xsd:ICMABondDataTaxonomy"
             xmlns:ext="urn:bdt-ext:manifest:v1">
  <bdt:Document>
    <bdt:ICMABondDataTaxonomy>
      <!-- standard BDT — independently valid against ICMA XSD -->
    </bdt:ICMABondDataTaxonomy>
  </bdt:Document>
  <ext:ExtensionManifest>
    <ext:Extension name="amortization" version="1.0"/>
  </ext:ExtensionManifest>
</BDTDocument>
```

The `<bdt:Document>` block is independently valid against the ICMA XSD. Extensions are siblings at the `BDTDocument` level, not injected into the BDT namespace.

**Two output modes:**

| Mode | Condition | Description |
|------|-----------|-------------|
| `done_valid` | All required BDT fields extracted and XSD-valid | Full, compliant output |
| `done_partial` | One or more required fields missing or invalid | Output returned with a `<ValidationWarnings>` block listing each gap; usable but flagged for review |

Jobs never return `failed` due to missing fields alone — partial output is always better than no output.

**Multi-bond output:** when a PDF yields N bonds, the result is a ZIP containing N XML files named by primary ISIN (e.g. `XS2524143554.xml`).

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
| No step-up / step-down coupon schedule | Cannot represent bonds where the interest rate changes on pre-defined dates (common in EM restructurings) | Custom `<StepCouponSchedule>` extension (planned v1.0) |

---

## Extension Framework

BDT v1.2 covers vanilla bonds well but leaves gaps for real-world structures. This project fills those gaps through a **versioned extension framework**. Extensions are designed to be separable from — and invisible to — the core BDT namespace, so the BDT core XML remains valid against the ICMA XSD.

### Extension conventions

- **Namespace pattern:** `urn:bdt-ext:{name}:v{major}` (e.g. `urn:bdt-ext:amortization:v1`)
- **Versioning:** each extension is versioned independently using semantic versioning. A major version bump indicates a breaking schema change.
- **Placement — two levels:**
  1. The `<ext:ExtensionManifest>` declaration lives at the outer `<BDTDocument>` wrapper level, as a sibling of `<bdt:Document>` (see Stage 6 output structure). This keeps the BDT core namespace clean — the ICMA XSD sees only a valid `<bdt:Document>` child.
  2. Extension data elements live inside the relevant BDT element using their own namespace (e.g. `<AmortizationSchedule xmlns="urn:bdt-ext:amortization:v1">` goes inside `<Product>`).

Full output structure with manifest (abbreviated):

```xml
<BDTDocument xmlns:bdt="urn:icma:xsd:ICMABondDataTaxonomy"
             xmlns:ext="urn:bdt-ext:manifest:v1">
  <bdt:Document>
    <bdt:ICMABondDataTaxonomy>
      <!-- standard BDT — independently valid against ICMA XSD -->
    </bdt:ICMABondDataTaxonomy>
  </bdt:Document>
  <ext:ExtensionManifest>
    <ext:Extension name="amortization" version="1.0" namespace="urn:bdt-ext:amortization:v1"/>
    <!-- additional extensions listed here as they are applied -->
  </ext:ExtensionManifest>
</BDTDocument>
```

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

### Step-up coupon extension (planned — v1.0)

BDT v1.2 has no mechanism to represent a coupon that steps up (or down) on pre-defined dates. This is common in EM sovereign and sub-sovereign bonds. 3 of 9 fixtures exhibit this structure (Argentina 2020, Buenos Aires Province 2021). A placeholder extension is planned:

```xml
<StepCouponSchedule xmlns="urn:bdt-ext:step-coupon:v1">
  <step>
    <stepDate>2024-08-21</stepDate>
    <rate>0.0875</rate>   <!-- 8.75% — rate from this date forward -->
  </step>
  <step>
    <stepDate>2026-08-21</stepDate>
    <rate>0.1000</rate>   <!-- 10.00% -->
  </step>
</StepCouponSchedule>
```

When applied, the manifest entry is: `<ext:Extension name="step-coupon" version="1.0" namespace="urn:bdt-ext:step-coupon:v1"/>`.

### Future extensions (placeholder)

New extensions are added here as they are designed. Each must follow the namespace/versioning convention above and document its schema alongside the implementation. Candidates:
- Floating rate reset schedule
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

| Component | Phase 1 — CLI (MVP) | Phase 2 — API service |
|-----------|--------------------|-----------------------|
| Entry point | `python convert.py <input.pdf> --output <dir>/` | FastAPI + file-based job queue |
| PDF parsing | `pymupdf` (fast, reliable on text PDFs) | + `docling` (layout-aware, OCR) |
| Heading detection | Fuzzy string match (rapidfuzz) | LLM classifier fallback |
| Summary table detection | Heuristic scan (line structure + keywords) | — |
| Field extraction | Small LLM via Ollama — JSON mode | HuggingFace TGI (swappable) |
| LLM model | Qwen2.5-7B or Phi-3.5-mini (32K+ context) | smollm3, Mistral 7B |
| Post-processing | `dateutil`, ISIN checksum, GLEIF API, rule-based | — |
| XML generation | Python `lxml` | — |
| XSD validation | `lxml` against BDT XSD | — |
| Job queue | — | File-based (watched dir) → Redis |
| Container | — | Docker + Docker Compose → Kubernetes |
| Testing | pytest + GeoPark PDF (simplest fixture) | Full regression suite |
| CI/CD | GitHub Actions | — |

---

## Test Fixtures

Test fixtures are real prospectus PDFs stored in `data/PDF/` (git-ignored). Each fixture is tagged with the bond features it exercises, to make it clear which test to run when working on a specific stage or extension.

### Current fixtures

| File | Pages | Issuer | Country | Bonds | Type | Currency | Maturity | Governing law | Source | Key features |
|------|-------|--------|---------|-------|------|----------|----------|---------------|--------|--------------|
| `REPUBLIC OF ARGENTINA Form 424B5 Filed 2020-08-17.pdf` | 221 | Republic of Argentina (sovereign) | Argentina | Multiple new series (2030, 2035, 2038…) | Fixed, amortizing, step-up | USD + EUR | 2029–2038 | New York | SEC EDGAR 424B5 | Multi-bond, amortizing, dual ISIN (144A + Reg S), exchange offer |
| `Prospectus - 2021.pdf` | 289 | Province of Buenos Aires | Argentina (sub-sovereign) | 6 series (USD A/B/C + EUR A/B/C, all due 2037) | Fixed step-up, amortizing | USD + EUR | 2037 | New York | LuxSE listing particulars | Multi-bond (6), amortizing (19–28 installments), step-up coupon, dual ISIN, dual currency, LEI: 549300L6AYROPOTQ4L07 |
| `us_prospectus_and_prospectus_supplement.pdf` | 374 | Republic of Argentina (sovereign) | Argentina | 4 types: Pars 2038, Discounts 2033, Quasi-Pars 2045, GDP-linked 2035 | Mixed + GDP-linked | USD | 2033–2045 | New York + Argentine | SEC EDGAR | Multi-bond (4), GDP-linked security, $81.8B exchange (2005 default restructuring) |
| `PDVSA_XS0294364103.pdf` | 220 | Petróleos de Venezuela S.A. (PDVSA) | Venezuela | 3 series: $3B 2017, $3B 2027, $1.5B 2037 | Fixed, bullet | USD | 2017/2027/2037 | New York | LuxSE | Multi-bond (3), guaranteed (PDVSA Petróleo), ISIN: XS0294364103, Venezuelan issuer (no BDT governing law match) |
| `USG38327AB13_OC_EN_2.PDF` | 191 | GeoPark Limited | Bermuda (LatAm operations) | 1 ($150M tap of $350M existing) | Fixed, bullet | USD | 2027 | New York | Private OM (144A / Reg S) | Single bond, tap issuance, CUSIP: G38327AB13, coupon 5.500% |
| `USL21779AD28_OC_EN_3.pdf` | 78 | CSN Resources S.A. (guaranteed by CSN Brazil) | Luxembourg / Brazil | 2 series: $600M 2026 + $400M 2023 tap | Fixed, bullet | USD | 2023/2026 | New York | Private OM (144A / Reg S) | Multi-bond (2), one is a tap, guaranteed, Luxembourg issuer, coupon 7.625% |
| `USP3710FAU86_OC_EN.PDF` | 154 | EDENOR S.A. (Argentine electricity utility) | Argentina | 1 ($135M) | Fixed, **amortizing** (3 installments) | USD | 2030 | New York | Private OM (144A / Reg S) | Amortizing (33%/33%/34% in Oct 2028/2029/2030), dual ISIN (Reg S: USP3710FAU86 / 144A: US29244AAM45), coupon 9.75% |
| `USP98047AC08_PR_EN.pdf` | 333 | Volcan Compañía Minera (Peruvian mining, Chungar guarantor) | Peru | 1 ($475M) | Fixed, bullet | USD | 2026 | New York | Listing memorandum | Single bond, guaranteed by subsidiaries, listing memorandum format, coupon 4.375%, ISIN: USP98047AC08 |
| `XS2278474924_OC_EN_2.pdf` | 622 | Liquid Telecommunications Financing plc | England & Wales / Africa | 1 ($620M) | Fixed, bullet, **senior secured** | USD | 2026 | English | Private OM (144A / Reg S) | Senior secured (unique in set), English law, African telecoms, largest doc (622 pages), ISIN: XS2278474924, coupon 5.5% |

### Feature coverage map

| Feature | Covered by |
|---------|-----------|
| Amortizing bonds | Argentina 2020, Buenos Aires Province 2021, EDENOR |
| Step-up coupon | Argentina 2020, Buenos Aires Province 2021 |
| Multi-bond prospectus | Argentina 2020, Buenos Aires Province 2021, Argentina 2005, PDVSA, CSN |
| Dual ISIN (144A + Reg S) | Argentina 2020, Buenos Aires Province 2021, EDENOR, GeoPark, CSN |
| Dual currency (USD + EUR) | Argentina 2020, Buenos Aires Province 2021 |
| GDP-linked security | Argentina 2005 |
| Guaranteed notes | PDVSA, CSN, Liquid Telecom, Volcan |
| Senior secured | Liquid Telecom |
| Tap issuance (fungible reopening) | GeoPark, CSN 2023 notes |
| English law | Liquid Telecom |
| New York law | All others |
| BDT governing law gap (no Venezuelan/Argentinian law) | PDVSA, EDENOR |
| Very large document (>300 pages) | Liquid Telecom (622), Argentina 2005 (374), Volcan (333) |
| Listing memorandum format | Volcan (USP98047AC08) |
| Sub-sovereign issuer | Buenos Aires Province 2021 |
| Vanilla single fixed-rate bullet (simplest case) | GeoPark, Liquid Telecom |

### Adding new fixtures

When adding a new PDF:
1. Place it in `data/PDF/` (git-ignored)
2. Add a row to both tables above
3. Add a pytest parametrize entry in the relevant test file
4. Gaps still worth covering: programme/EMTN issuance, floating rate, non-English/non-NY governing law (French, German)

---

## Future Steps

Items deferred from MVP, in rough priority order:

1. **OCR support** — some PDF prospectuses are scans; requires `docling` or `easyocr` in the parsing stage
2. **Redis job queue** — replace file-based queue for production robustness and horizontal scaling (Phase 2)
3. **ACTUS integration** — use the ACTUS standard to algorithmically validate or derive the amortization schedule from contract terms
4. **Step-up coupon extraction** — design and implement the `StepCouponSchedule` extension (3 of 9 fixtures require it)
5. **Floating rate bond support** — BDT has `FloatingRatePayment` in the schema but field extraction for floating rate terms requires different prompt groups
6. **BDT enum extension proposals** — engage ICMA to propose additions: more business day centers (Buenos Aires, Singapore, Tokyo), more governing laws (Argentinian, Singapore), more clearing systems (Caja de Valores, CDP)
7. **Confidence scoring** — each extracted field should carry a confidence score; low-confidence fields flagged for human review
8. **Diff / update mode** — given an existing BDT XML and a new PDF, emit only the changed fields
9. **UI / Gradio front-end** — simple interface for uploading PDFs and downloading XMLs

---

## Resources

- [ICMA Bond Data Taxonomy](https://www.icmagroup.org/fintech-and-digitalisation/fintech-advisory-committee-and-related-groups/bond-data-taxonomy/) — BDT Pack v1.2 download (XSD, user guide, XML examples)
- [FpML `notionalStepSchedule`](https://schemas.liquid-technologies.com/FpML/5.9/confirmation/notionalstepschedule.html) — reference for amortization extension pattern
- [ACTUS Standard](https://www.actusfrf.org/) — algorithmic contract type standard
- `.docs/ICMA-Bond-Data-Taxonomy-v1.2-2024-02-02/` — local copy of BDT Pack (XSD files, example XMLs, user guide)
- `.docs/amortization_standard.MD` — rationale for FpML + ACTUS approach for amortizing bonds
