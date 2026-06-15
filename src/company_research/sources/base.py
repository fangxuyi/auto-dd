from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from company_research.models.identity import CompanyIdentity
from company_research.models.sources import NormalizedDocument, RawDocument, SourceRecord


@runtime_checkable
class SourceAdapter(Protocol):
    def search(self, company: CompanyIdentity, cutoff: date) -> list[SourceRecord]: ...
    def fetch(self, source: SourceRecord) -> RawDocument: ...
    def normalize(self, document: RawDocument) -> NormalizedDocument: ...
