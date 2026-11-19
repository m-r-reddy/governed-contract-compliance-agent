"""Markdown-aware contract section chunker preserving ACL and structural metadata."""

from __future__ import annotations

import re

from src.core.exceptions import DomainValidationError, TenantAccessDeniedError
from src.domain.context import TenantContext
from src.domain.contract import ContractChunk, ContractTerms

_HEADER_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def _classify_clause(section_header: str) -> str:
    """Infer semantic clause category from the Markdown section title."""
    normalized = section_header.lower()
    if any(token in normalized for token in ("rate", "pricing", "fee", "compensation")):
        return "rate_card"
    if any(token in normalized for token in ("scope", "deliverable", "milestone", "statement")):
        return "scope"
    if any(token in normalized for token in ("payment", "invoice", "billing", "term")):
        return "payment_terms"
    return "general"


class MarkdownContractChunker:
    """Deterministic Markdown header splitter for MSAs and SOWs."""

    def __init__(self, max_chars: int = 1600, overlap_chars: int = 200) -> None:
        if overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be strictly less than max_chars")
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    def chunk_contract(
        self,
        terms: ContractTerms,
        markdown_body: str,
        context: TenantContext,
    ) -> list[ContractChunk]:
        """Split a contract into ACL-tagged ContractChunk domain records."""
        if terms.tenant_id != context.tenant_id:
            raise TenantAccessDeniedError(
                f"Contract tenant '{terms.tenant_id}' does not match "
                f"authenticated context tenant '{context.tenant_id}'.",
                correlation_id=context.correlation_id,
            )

        cleaned = markdown_body.strip()
        if not cleaned:
            raise DomainValidationError(
                "Cannot chunk empty contract markdown body.",
                correlation_id=context.correlation_id,
            )

        sections = self._split_by_headers(cleaned)
        chunks: list[ContractChunk] = []
        chunk_idx = 0

        for header, body in sections:
            for window in self._window_text(body):
                chunks.append(
                    ContractChunk(
                        chunk_id=f"{terms.contract_id}:chk:{chunk_idx:04d}",
                        tenant_id=context.tenant_id,
                        contract_id=terms.contract_id,
                        vendor_id=terms.vendor_id,
                        department_acl=list(terms.department_acl),
                        section_header=header[:256],
                        clause_type=_classify_clause(header),
                        chunk_index=chunk_idx,
                        content=window,
                        metadata={
                            "contract_title": terms.title,
                            "effective_start": terms.effective_window.start_date.isoformat(),
                            "effective_end": terms.effective_window.end_date.isoformat(),
                        },
                    )
                )
                chunk_idx += 1

        return chunks

    def _split_by_headers(self, text: str) -> list[tuple[str, str]]:
        matches = list(_HEADER_PATTERN.finditer(text))
        if not matches:
            return [("General Provisions", text)]

        sections: list[tuple[str, str]] = []
        if matches[0].start() > 0:
            preamble = text[: matches[0].start()].strip()
            if preamble:
                sections.append(("Preamble", preamble))

        for idx, match in enumerate(matches):
            header_title = match.group(2).strip()
            body_start = match.end()
            body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            section_text = text[body_start:body_end].strip()
            if section_text:
                sections.append((header_title, section_text))

        return sections

    def _window_text(self, text: str) -> list[str]:
        if len(text) <= self._max_chars:
            return [text]

        windows: list[str] = []
        step = self._max_chars - self._overlap_chars
        start = 0
        while start < len(text):
            slice_text = text[start : start + self._max_chars].strip()
            if slice_text:
                windows.append(slice_text)
            start += step
        return windows
