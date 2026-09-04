"""Evidence records used by normalized facts and decisions."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    """Strict base model that preserves the contract's camelCase wire names."""

    model_config = ConfigDict(
        alias_generator=_camel,
        extra="forbid",
        populate_by_name=True,
        strict=True,
    )


def _validate_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("evidence values must be finite JSON values")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("evidence object keys must be strings")
        for child in value.values():
            _validate_json_value(child)
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _validate_json_value(child)
        return value
    raise ValueError("evidence value is not JSON-compatible")


class EvidenceItem(ContractModel):
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    value: Any
    source_url: str
    api_source: str = Field(min_length=1)
    observed_at: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: Any) -> Any:
        return _validate_json_value(value)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("invalid absolute URL")
        return value

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: str) -> str:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise ValueError("invalid ISO datetime") from error
        if parsed.tzinfo is None:
            raise ValueError("ISO datetime must include an offset")
        return value


class EvidenceBuilder:
    """Insertion-ordered evidence builder with duplicate-ID rejection."""

    def __init__(self, observed_at: str, default_source_url: str) -> None:
        self._observed_at = observed_at
        self._default_source_url = default_source_url
        self._items: dict[str, EvidenceItem] = {}

    def add(
        self,
        evidence_id: str,
        category: str,
        claim: str,
        value: Any,
        api_source: str,
        source_url: str | None = None,
    ) -> str:
        if evidence_id in self._items:
            raise ValueError(f"Duplicate evidence id: {evidence_id}")
        item = EvidenceItem.model_validate(
            {
                "id": evidence_id,
                "category": category,
                "claim": claim,
                "value": value,
                "sourceUrl": source_url or self._default_source_url,
                "apiSource": api_source,
                "observedAt": self._observed_at,
            }
        )
        self._items[evidence_id] = item
        return evidence_id

    def values(self) -> list[EvidenceItem]:
        return list(self._items.values())
