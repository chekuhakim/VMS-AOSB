"""Vendor RFQ declaration wording — edit the text here only.

Bump DECLARATION_VERSION whenever the wording changes so every stored quotation
records exactly which version the vendor accepted (ISO evidence).
"""

from __future__ import annotations

DECLARATION_VERSION = "2026-09-v1"

DECLARATION_TEMPLATE = (
    "I declare that this quotation is submitted on behalf of {company}, that the "
    "information and prices provided are true and accurate, that we have read and "
    "accept the RFQ scope and terms, that the quotation remains valid for the stated "
    "period, and that we have no conflict of interest with Alpha Orange Sdn Bhd or "
    "its staff and have not colluded with other bidders."
)


def declaration_text(company_name: str) -> str:
    return DECLARATION_TEMPLATE.format(company=company_name)
