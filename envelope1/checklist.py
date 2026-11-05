"""Envelope 1 checklist metadata (item grouping, help text, wording)."""

from __future__ import annotations

from envelope1.models import Envelope1Document, Envelope1Item

# Help text shown beside each item (info icon tooltip)
ITEM_HELP: dict[str, str] = {
    Envelope1Item.SIGNED_MSA: "Upload the MSA PDF you signed after downloading the draft.",
    Envelope1Item.FINANCIAL_STATEMENTS: (
        "Audited financial statements for at least the last two financial years — "
        "one PDF per year."
    ),
    Envelope1Item.BANK_FACILITY: (
        "Letter or statement evidencing a bank credit facility / overdraft arrangement."
    ),
    Envelope1Item.SUPPLIER_CREDIT: (
        "Proof of supplier credit terms currently available to your company."
    ),
    Envelope1Item.NO_ADVANCE: (
        "Download the declaration, sign it, then upload the signed PDF."
    ),
    Envelope1Item.CAR_INSURANCE: (
        "Contractor's All Risk (CAR) insurance certificate covering typical site works."
    ),
    Envelope1Item.PRIMARY_SUPPLIERS: (
        "List the main structures you supply and the supplier for each."
    ),
    Envelope1Item.LEAD_TIME: (
        "Choose the typical Sabah delivery range. Only required if you are interested in Sabah work."
    ),
    Envelope1Item.SITE_SUPERVISOR: (
        "Full name of the dedicated site supervisor assigned to Alpha Orange works."
    ),
    Envelope1Item.QUALITY_PLAN: (
        "Quality management plan covering inspection and non-conformance handling."
    ),
    Envelope1Item.HSE_PLAN: "Health & safety (HSE) plan aligned to site work under the MSA.",
    Envelope1Item.PAST_PROJECTS: "One row per project, each with a supporting PDF.",
    Envelope1Item.CLIENT_REFERENCES: (
        "Client reference contacts willing to confirm past performance."
    ),
    Envelope1Item.ORG_CHART: "Your company's current organisation chart.",
}

# Step → checklist items Procurement evaluates (vendor wizard order)
STEP_ITEMS: dict[int, list[str]] = {
    2: [Envelope1Item.SIGNED_MSA],
    3: [
        Envelope1Item.FINANCIAL_STATEMENTS,
        Envelope1Item.BANK_FACILITY,
        Envelope1Item.SUPPLIER_CREDIT,
        Envelope1Item.NO_ADVANCE,
        Envelope1Item.CAR_INSURANCE,
    ],
    4: [
        Envelope1Item.SABAH_INTEREST,
        Envelope1Item.PRIMARY_SUPPLIERS,
        Envelope1Item.LEAD_TIME,
    ],
    5: [
        Envelope1Item.SITE_SUPERVISOR,
        Envelope1Item.TIMESTAMPED_REPORTING,
        Envelope1Item.METMALAYSIA_EOT,
        Envelope1Item.QUALITY_PLAN,
        Envelope1Item.HSE_PLAN,
    ],
    6: [
        Envelope1Item.PAST_PROJECTS,
        Envelope1Item.CLIENT_REFERENCES,
        Envelope1Item.ORG_CHART,
    ],
}

ALL_ITEMS: list[str] = [item for items in STEP_ITEMS.values() for item in items]

# Yes/No questions whose "Yes" answer requires a PDF upload: item → (submission field, doc type)
YES_NO_UPLOADS: dict[str, tuple[str, str]] = {
    Envelope1Item.BANK_FACILITY: ("has_bank_facility", Envelope1Document.DocType.BANK_FACILITY),
    Envelope1Item.SUPPLIER_CREDIT: (
        "has_supplier_credit",
        Envelope1Document.DocType.SUPPLIER_CREDIT,
    ),
    Envelope1Item.QUALITY_PLAN: ("has_quality_plan", Envelope1Document.DocType.QUALITY_PLAN),
    Envelope1Item.HSE_PLAN: ("has_hse_plan", Envelope1Document.DocType.HSE_PLAN),
    Envelope1Item.CLIENT_REFERENCES: (
        "has_client_references",
        Envelope1Document.DocType.CLIENT_REFERENCES,
    ),
}

# Always-required single uploads: item → doc type
REQUIRED_UPLOADS: dict[str, str] = {
    Envelope1Item.SIGNED_MSA: Envelope1Document.DocType.SIGNED_MSA,
    Envelope1Item.NO_ADVANCE: Envelope1Document.DocType.NO_ADVANCE,
    Envelope1Item.CAR_INSURANCE: Envelope1Document.DocType.CAR_INSURANCE,
    Envelope1Item.ORG_CHART: Envelope1Document.DocType.ORG_CHART,
}

# Types that require an expiry date on upload
EXPIRY_REQUIRED_TYPES: set[str] = {
    Envelope1Document.DocType.CAR_INSURANCE,
}

QUESTIONS: dict[str, str] = {
    Envelope1Item.BANK_FACILITY: "Does your company have a bank credit facility or overdraft?",
    Envelope1Item.SUPPLIER_CREDIT: "Does your company have supplier credit terms?",
    Envelope1Item.SABAH_INTEREST: "Is your company interested in carrying out work in Sabah?",
    Envelope1Item.QUALITY_PLAN: "Does your company have a Quality Management Plan?",
    Envelope1Item.HSE_PLAN: "Does your company have a Health & Safety (HSE) Plan?",
    Envelope1Item.PAST_PROJECTS: "Does your company have a list of past projects?",
    Envelope1Item.CLIENT_REFERENCES: "Does your company have client references?",
}

DECLARATIONS: dict[str, str] = {
    Envelope1Item.TIMESTAMPED_REPORTING: (
        "I confirm that my company will submit site progress reports with timestamped "
        "photographs, in the format and frequency required by Alpha Orange, for all work "
        "carried out under this MSA."
    ),
    Envelope1Item.METMALAYSIA_EOT: (
        "I acknowledge that any extension of time (EOT) claimed due to weather will only be "
        "considered if supported by official Malaysian Meteorological Department (MetMalaysia) "
        "records for the site location and period concerned."
    ),
}

LEAD_TIME_DESCRIPTION = "Typical time from purchase order to structure on site for Sabah work."
LEAD_TIME_RANGE_LABEL = "Typical Sabah delivery lead time"
# Legacy labels: kept so older submissions with exact-day values still display.
LEAD_TIME_SEA_LABEL = "Sabah sea freight to Kota Kinabalu"
LEAD_TIME_SEMENANJUNG_LABEL = "Semenanjung delivery to the site"

MIN_FINANCIAL_STATEMENTS = 2

STEP_META: dict[int, dict[str, str]] = {
    1: {
        "title": "MSA party details",
        "short": "MSA Party",
        "hint": "Details used to generate the draft Master Service Agreement.",
    },
    2: {
        "title": "Upload signed Master Service Agreement",
        "short": "Signed Master Service Agreement",
        "hint": "Download the draft MSA, sign it, then upload the signed PDF.",
    },
    3: {
        "title": "Statutory evidence & financials",
        "short": "Financials",
        "hint": "Financial statements, credit arrangements, and insurance.",
    },
    4: {
        "title": "Logistics",
        "short": "Logistics",
        "hint": "Sabah coverage, primary suppliers, and delivery lead time.",
    },
    5: {
        "title": "Quality, safety & governance",
        "short": "Quality & HSE",
        "hint": "Site supervision, reporting commitments, quality and HSE plans.",
    },
    6: {
        "title": "Track record & organisation",
        "short": "Track record",
        "hint": "Past projects, client references, and organisation chart — then submit.",
    },
}
