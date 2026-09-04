"""Raw GitHub acquisition types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gitnext.domain.facts import Source, SourceAvailability


@dataclass
class OptionalRawSource:
    available: bool
    data: Any
    availability: SourceAvailability | None = None
    limitation: str | None = None
    truncated: bool = False


@dataclass
class RawGitHubData:
    source: Source
    fetched_at: str
    repository: Any
    item: Any
    compare: OptionalRawSource
    check_runs: OptionalRawSource
    commit_statuses: OptionalRawSource
    reviews: OptionalRawSource
    comments: OptionalRawSource
    commits: OptionalRawSource
    graphql: OptionalRawSource
    rate_limit_remaining: int | None
    limitations: list[str]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RawGitHubData:
        def source(name: str) -> OptionalRawSource:
            raw = value[name]
            if not isinstance(raw, dict) or not isinstance(raw.get("available"), bool):
                raise ValueError(f"invalid raw source: {name}")
            availability = raw.get("availability")
            return OptionalRawSource(
                available=raw["available"],
                data=raw.get("data"),
                availability=availability,
                limitation=raw.get("limitation"),
                truncated=raw.get("truncated") is True,
            )

        raw_limitations = value.get("limitations")
        if not isinstance(raw_limitations, list) or not all(isinstance(item, str) for item in raw_limitations):
            raise ValueError("invalid raw limitations")
        fetched_at = value.get("fetchedAt")
        if not isinstance(fetched_at, str):
            raise ValueError("invalid raw fetchedAt")
        rate_limit = value.get("rateLimitRemaining")
        if rate_limit is not None and (not isinstance(rate_limit, int) or isinstance(rate_limit, bool)):
            raise ValueError("invalid raw rateLimitRemaining")
        return cls(
            source=Source.model_validate(value["source"]),
            fetched_at=fetched_at,
            repository=value.get("repository"),
            item=value.get("item"),
            compare=source("compare"),
            check_runs=source("checkRuns"),
            commit_statuses=source("commitStatuses"),
            reviews=source("reviews"),
            comments=source("comments"),
            commits=source("commits"),
            graphql=source("graphql"),
            rate_limit_remaining=rate_limit,
            limitations=list(raw_limitations),
        )
