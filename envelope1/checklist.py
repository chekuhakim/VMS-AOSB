"""Envelope 1 document checklist metadata (tooltips + step grouping)."""

from __future__ import annotations

from envelope1.models import Envelope1Document

# Help text shown beside each upload (info icon tooltip)
DOC_HELP: dict[str, str] = {
    Envelope1Document.DocType.SIGNED_MSA: (
        "Upload the MSA PDF you signed after downloading the draft. "
        "Effective date must match the date shown on the signed document."
    ),
    Envelope1Document.DocType.AUDITED_FINANCIALS: (
        "Audited financial statements for the last two financial years. "
        "Expiry should reflect the validity window of the latest set."
    ),
    Envelope1Document.DocType.BANK_FACILITY: (
        "Letter or statement evidencing bank credit facility / overdraft arrangement."
    ),
    Envelope1Document.DocType.SUPPLIER_CREDIT: (
        "Proof of supplier credit terms currently available to your company."
    ),
    Envelope1Document.DocType.NO_ADVANCE: (
        "Signed declaration that no advance payment is required for works under this MSA."
    ),
    Envelope1Document.DocType.CAR_INSURANCE: (
        "Contractor's All Risk (CAR) insurance certificate covering typical site works."
    ),
    Envelope1Document.DocType.FREIGHT_FORWARDER: (
        "Named freight forwarder details for inbound materials logistics."
    ),
    Envelope1Document.DocType.PRIMARY_SUPPLIERS: (
        "Primary supplier list covering critical materials and equipment."
    ),
    Envelope1Document.DocType.SABAH_BACKUP: (
        "Local Sabah backup suppliers that can cover short-notice shortages."
    ),
    Envelope1Document.DocType.LEAD_TIME_MATRIX: (
        "Lead-time matrix for key materials from order to site delivery."
    ),
    Envelope1Document.DocType.SITE_SUPERVISOR_CV: (
        "CV of the dedicated site supervisor assigned to Alpha Orange works."
    ),
    Envelope1Document.DocType.TIMESTAMPED_REPORTING: (
        "Agreement to provide timestamped progress / photo reporting as required."
    ),
    Envelope1Document.DocType.METMALAYSIA_EOT: (
        "MetMalaysia EOT (extension of time) weather-related agreement acknowledgement."
    ),
    Envelope1Document.DocType.QUALITY_PLAN: (
        "Quality management plan covering inspection and non-conformance handling."
    ),
    Envelope1Document.DocType.HSE_PLAN: (
        "Health & safety (HSE) plan aligned to site work under the MSA."
    ),
    Envelope1Document.DocType.PAST_PROJECTS: (
        "Past project list with client, scope, value, and completion year."
    ),
    Envelope1Document.DocType.CLIENT_REFERENCES: (
        "Client reference contacts willing to confirm past performance."
    ),
    Envelope1Document.DocType.MANPOWER_MATRIX: (
        "Specialized manpower matrix (roles, headcount, certifications)."
    ),
}

# Step → required document types (step 2 = MSA only; 3–6 = packs)
STEP_DOC_TYPES: dict[int, list[str]] = {
    2: [Envelope1Document.DocType.SIGNED_MSA],
    3: [
        Envelope1Document.DocType.AUDITED_FINANCIALS,
        Envelope1Document.DocType.BANK_FACILITY,
        Envelope1Document.DocType.SUPPLIER_CREDIT,
        Envelope1Document.DocType.NO_ADVANCE,
        Envelope1Document.DocType.CAR_INSURANCE,
    ],
    4: [
        Envelope1Document.DocType.FREIGHT_FORWARDER,
        Envelope1Document.DocType.PRIMARY_SUPPLIERS,
        Envelope1Document.DocType.SABAH_BACKUP,
        Envelope1Document.DocType.LEAD_TIME_MATRIX,
    ],
    5: [
        Envelope1Document.DocType.SITE_SUPERVISOR_CV,
        Envelope1Document.DocType.TIMESTAMPED_REPORTING,
        Envelope1Document.DocType.METMALAYSIA_EOT,
        Envelope1Document.DocType.QUALITY_PLAN,
        Envelope1Document.DocType.HSE_PLAN,
    ],
    6: [
        Envelope1Document.DocType.PAST_PROJECTS,
        Envelope1Document.DocType.CLIENT_REFERENCES,
        Envelope1Document.DocType.MANPOWER_MATRIX,
    ],
}

# Types that require an expiry date on upload
EXPIRY_REQUIRED_TYPES: set[str] = {
    Envelope1Document.DocType.AUDITED_FINANCIALS,
    Envelope1Document.DocType.CAR_INSURANCE,
}

STEP_META: dict[int, dict[str, str]] = {
    1: {
        "title": "MSA party details",
        "short": "MSA Party",
        "hint": "Details used to generate the draft Master Service Agreement.",
    },
    2: {
        "title": "Upload signed MSA",
        "short": "Signed MSA",
        "hint": "Download the draft MSA, sign it, then upload the signed PDF.",
    },
    3: {
        "title": "Statutory evidence & financials",
        "short": "Financials",
        "hint": "Upload statutory and financial evidence packs (PDF).",
    },
    4: {
        "title": "Logistics",
        "short": "Logistics",
        "hint": "Freight, suppliers, and lead-time evidence.",
    },
    5: {
        "title": "Quality, safety & governance",
        "short": "Quality & HSE",
        "hint": "Site supervision, quality, and HSE documentation.",
    },
    6: {
        "title": "Track record & manpower",
        "short": "Track record",
        "hint": "Past projects, references, and manpower matrix — then submit.",
    },
}
