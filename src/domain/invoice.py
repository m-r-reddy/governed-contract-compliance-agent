"""Canonical vendor invoice domain entities and financial invariants."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DateRange(BaseModel):
    """Validated service billing window."""

    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_chronological_order(self) -> DateRange:
        if self.end_date < self.start_date:
            raise ValueError(
                f"end_date ({self.end_date}) cannot precede start_date ({self.start_date})"
            )
        return self


class InvoiceLineItem(BaseModel):
    """Single billable line item enforced with deterministic Decimal arithmetic."""

    model_config = ConfigDict(frozen=True)

    description: str = Field(min_length=3, max_length=500)
    role_title: str | None = Field(default=None, max_length=128)
    rate: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)
    hours: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)
    subtotal: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)

    @model_validator(mode="after")
    def validate_line_arithmetic(self) -> InvoiceLineItem:
        expected = (self.rate * self.hours).quantize(Decimal("0.01"))
        if abs(self.subtotal - expected) > Decimal("0.01"):
            raise ValueError(
                f"Line item subtotal mismatch: got {self.subtotal}, "
                f"expected {expected} ({self.rate} * {self.hours})"
            )
        return self


class InvoicePayload(BaseModel):
    """Multi-tenant vendor invoice contract validated prior to compliance audit."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(default="org_default", min_length=2, max_length=64)
    invoice_id: str = Field(min_length=3, max_length=64)
    vendor_id: str = Field(min_length=2, max_length=64)
    purchase_order_id: str = Field(min_length=3, max_length=64)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    billing_period: DateRange
    line_items: list[InvoiceLineItem] = Field(min_length=1)
    total_amount: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)
    memo: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_invoice_total(self) -> InvoicePayload:
        computed_total = sum(
            (item.subtotal for item in self.line_items), start=Decimal("0.00")
        ).quantize(Decimal("0.01"))
        if abs(self.total_amount - computed_total) > Decimal("0.01"):
            raise ValueError(
                f"Invoice total_amount ({self.total_amount}) does not match "
                f"sum of line items ({computed_total})"
            )
        return self
