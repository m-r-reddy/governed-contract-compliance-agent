"""Port interfaces for outbound AI model gateway operations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.context import TenantContext
from src.domain.invoice import InvoicePayload


@runtime_checkable
class InvoiceExtractorProtocol(Protocol):
    """Contract for extracting structured InvoicePayload records from raw text."""

    async def parse_raw_invoice(
        self, raw_text: str, context: TenantContext
    ) -> InvoicePayload: ...
