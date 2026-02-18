"""
BDT v1.2 enumeration constants.

All allowed values for XSD-restricted fields.  These are the *exact* strings
that must appear in the output XML.  The LLM is given these lists in prompts
so it can map prospectus text → enum value directly.
"""

ISSUANCE_TYPE = ["PROGRAMME", "STANDALONE"]

STATUS_OF_NOTE = [
    "SENIOR_SECURED",
    "SENIOR_UNSECURED",
    "SENIOR_PREFERRED",
    "SENIOR_NON_PREFERRED",
    "SUBORDINATED",
]

FORM_OF_NOTE = [
    "BEARER",
    "REGISTERED",
    "DEMATERIALISED",
    "BOOK_ENTRY",
    "FED_BOOK_ENTRY",
    "MATERIALISED_BEARER",
    "MATERIALISED_REGISTERED",
    "DEMATERIALISED_BEARER",
    "DEMATERIALISED_BOOK_ENTRY",
    "DEMATERIALISED_REGISTERED",
    "UNCERTIFICATED_DEMATERIALISED_BOOK_ENTRY",
    "UNCERTIFICATED_REGISTERED",
    "UNCERTIFIED",
    "UNCERTIFIED_DEMATERIALISED_BOOK_ENTRY",
    "COLLECTIVE_DEBT_REGISTERED_CLAIM",
]

INTEREST_TYPE = ["FIXED", "FLOATING", "ZERO_COUPON", "INDEX_LINKED_INTEREST"]

INTEREST_PAYMENT_FREQUENCY = ["ANNUALLY", "SEMIANNUALLY", "QUARTERLY", "NONE"]

DAY_COUNT_FRACTION = [
    "ICMA_ACT/ACT",
    "ISDA_ACT/ACT",
    "30/360",
    "30/365",
    "ACT/360",
    "ACT/365",
]

BUSINESS_DAY_CONVENTION = [
    "FOLLOWING_UNADJUSTED",
    "PRECEDING",
    "MODIFIED_FOLLOWING_ADJUSTED",
]

# NOTE: only 5 options — Buenos Aires, Tokyo, Singapore etc. are NOT in BDT v1.2.
# Workaround: use NEW_YORK for USD bonds; document gap in ValidationWarnings.
BUSINESS_DAY_CENTER = ["TARGET", "TARGET2", "FRANKFURT", "NEW_YORK", "LUXEMBOURG"]

# NOTE: only 15 options — Argentinian law, Singapore law etc. are NOT in BDT v1.2.
# Workaround: use NEW_YORK_LAW for EM international tranches.
GOVERNING_LAW = [
    "AUSTRIAN_LAW",
    "BELGIAN_LAW",
    "CANADIAN_LAW",
    "DANISH_LAW",
    "DUTCH_LAW",
    "ENGLISH_LAW",
    "FINISH_LAW",
    "FRENCH_LAW",
    "GERMAN_LAW",
    "ITALIAN_LAW",
    "LUXEMBOURG_LAW",
    "NEW_SOUTH_WALES_LAW",
    "NEW_YORK_LAW",
    "ONTARIO_LAW",
    "SPANISH_LAW",
]

SELLING_RESTRICTION_CODE = [
    "REGS_CAT1",
    "REGS_CAT2",
    "REGS_CAT3",
    "144A",
    "TEFRA_C",
    "TEFRA_D",
    "TEFRA_NA",
    "SEC_REG",
    "NOT_APPLICABLE",
]

CLEARING_SETTLEMENT_SYSTEM = [
    "CLEARSTREAM_BANKING_FRANKFURT",
    "DTCC",
    "EUROCLEAR_BANK_SA/NV",
    "CLEARSTREAM_BANKING_S.A.",
    "CENTRAL_MONEY_MARKETS_UNIT",
]

REDEMPTION_PAYMENT_BASIS = [
    "PAR",
    "PARTLY_PAID",
    "INDEX_LINKED_INTEREST",
    "INSTALLMENT",
    "DUAL_CURRENCY",
]

RATING_AGENCY = ["FITCH", "MOODYS", "SP", "DBRS"]

RATING_OUTLOOK = [
    "POSITIVE",
    "STABLE",
    "NEGATIVE",
    "DEVELOPING",
    "NOT_MEANINGFULL",
    "EVOLVING",
    "NOT_APPLICABLE",
]

MANUFACTURER_TARGET_MARKET = [
    "EU_MIFIDII_PROF_AND_ECPS",
    "EU_MIFIR_PROF_AND_ECPS",
    "UK_MIFIR_PROF_AND_ECPS",
    "EU_MIFIDII_RETAIL_PROF_ECPS",
    "UK_MIFIR_RETAIL_PROF_ECPS",
    "NOT_APPLICABLE",
]

PARTY_ROLE_TYPE = [
    "ISSUER",
    "GUARANTOR",
    "LEAD_MANAGER",
    "JOINT_LEAD_MANAGER",
    "ARRANGER",
    "FISCAL_AGENT",
    "PRINCIPAL_PAYING_AGENT",
    "CALCULATION_AGENT",
    "STABILISATION_MANAGER",
    "TRUSTEE",
    "REGISTRAR",
    "CUSTODIAN",
    "PAYING_AGENT",
    "TRANSFER_AGENT",
    "ISSUE_AGENT",
    "LEGAL_ADVISOR",
    "LODGING_AGENT",
    "CENTRAL_ACCOUNT_KEEPER",
    "TOKENISATION_MANAGER",
    "CRYPTO_SECURITIES_REGISTRAR",
    "JOINT_GLOBAL_COORDINATOR",
    "JOINT_BOOKRUNNER",
    "MARKET_PRACTICE_ADVISOR",
    "DIRECT_PARTICIPANT",
    "DEPOSIT_BANK",
    "CASH_TOKEN_MANAGER",
    "PLATFORM_OPERATOR",
    "OTHER_PARTYROLE_TYPE",
]

# ---------------------------------------------------------------------------
# LLM field groups
# Each group is sent as a separate prompt in Stage 5b.
# Keys become the JSON keys the LLM must return.
# ---------------------------------------------------------------------------

FIELD_GROUPS = {
    "identifiers": {
        "description": "Security identifiers",
        "fields": {
            "isin": "ISIN code (12-char, e.g. XS2385150334)",
            "cusip": "CUSIP code (9-char) if present, else null",
            "common_code": "Common Code (9-digit Euroclear/Clearstream) if present, else null",
            "sedol": "SEDOL (7-char) if present, else null",
        },
    },
    "amounts": {
        "description": "Principal amounts and denomination",
        "fields": {
            "aggregate_nominal_amount": "Total face value of the issue (numeric, no symbols)",
            "specified_denomination": "Minimum denomination per note (numeric)",
            "integral_multiples": "Integral multiples above denomination (numeric), or null",
            "specified_currency": "ISO 4217 currency code (e.g. USD, EUR)",
        },
    },
    "dates": {
        "description": "Key dates",
        "fields": {
            "pricing_date": "Trade/pricing date (YYYY-MM-DD)",
            "issue_date": "Issue/settlement date (YYYY-MM-DD)",
            "settlement_date": "Settlement date if different from issue date (YYYY-MM-DD), else same as issue_date",
            "maturity_date": "Final maturity date (YYYY-MM-DD)",
            "interest_commencement_date": "Date from which interest accrues (YYYY-MM-DD)",
        },
    },
    "interest": {
        "description": "Coupon and day count terms",
        "fields": {
            "interest_type": f"One of: {INTEREST_TYPE}",
            "interest_rate": "Annual interest rate as decimal (e.g. 0.055 for 5.5%), or null if not fixed",
            "interest_payment_frequency": f"One of: {INTEREST_PAYMENT_FREQUENCY}",
            "day_count_fraction": f"One of: {DAY_COUNT_FRACTION}",
            "business_day_convention": f"One of: {BUSINESS_DAY_CONVENTION}",
            "business_day_center": f"One of: {BUSINESS_DAY_CENTER}. Use NEW_YORK for USD bonds if exact center not listed.",
            "first_interest_payment_date": "Date of first coupon payment (YYYY-MM-DD)",
        },
    },
    "issuance": {
        "description": "Issuance terms",
        "fields": {
            "issuance_type": f"One of: {ISSUANCE_TYPE}. Use STANDALONE unless document references a programme/MTN.",
            "issue_price": "Issue price as percentage of par (e.g. 100.0 for par, 98.5 for discount)",
            "form_of_note": f"One of: {FORM_OF_NOTE}",
            "status_of_note": f"One of: {STATUS_OF_NOTE}",
            "governing_law": f"One of: {GOVERNING_LAW}. Use NEW_YORK_LAW for EM bonds if exact law not listed.",
            "redemption_payment_basis": f"One of: {REDEMPTION_PAYMENT_BASIS}. Use INSTALLMENT if the bond amortizes.",
            "listing_market": "Name of the stock exchange where listed (free text), or NOT_LISTED",
        },
    },
    "parties": {
        "description": "Issuer and key deal parties (names only — LEI resolved separately)",
        "fields": {
            "issuer_name": "Full legal name of the bond issuer",
            "guarantor_name": "Full legal name of guarantor if present, else null",
            "lead_managers": "List of lead manager / joint bookrunner names",
            "trustee": "Name of the trustee / indenture trustee, or null",
            "fiscal_agent": "Name of the fiscal agent, or null",
            "principal_paying_agent": "Name of the principal paying agent, or null",
        },
    },
    "restrictions": {
        "description": "Selling restrictions",
        "fields": {
            "selling_restrictions": f"List of applicable codes from: {SELLING_RESTRICTION_CODE}",
            "priips_restriction": "true if PRIIPs KID restriction applies (EU retail), false otherwise",
        },
    },
}

# Amortization fields — only used when redemption_payment_basis == INSTALLMENT
AMORTIZATION_FIELDS = {
    "description": "Principal repayment schedule for amortizing bonds",
    "fields": {
        "amortization_steps": (
            "List of objects with stepDate (YYYY-MM-DD) and stepValue (outstanding "
            "notional in nominal currency AFTER payment on that date, numeric). "
            "Last step should have stepValue = 0 (full redemption)."
        )
    },
}
