"""Pydantic representation of the frozen GitNext v1 facts contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from gitnext.domain.evidence import ContractModel, EvidenceItem

FACTS_SCHEMA_VERSION = "1.0.0"

ItemKind = Literal["ISSUE", "PULL_REQUEST"]
CheckStatus = Literal["SUCCESS", "FAILURE", "PENDING", "NEUTRAL", "CANCELLED", "SKIPPED", "UNKNOWN"]
ReviewState = Literal["APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING", "UNKNOWN"]
ReviewDecision = Literal["APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED", "UNKNOWN"]
SourceAvailability = Literal["AVAILABLE", "NOT_APPLICABLE", "UNAVAILABLE", "RATE_LIMITED", "FORBIDDEN", "TRUNCATED"]


def _validate_url(value: str) -> str:
    from urllib.parse import urlsplit

    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid absolute URL")
    return value


def _validate_datetime(value: str) -> str:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ValueError("invalid ISO datetime") from error
    if parsed.tzinfo is None:
        raise ValueError("ISO datetime must include an offset")
    return value


class Source(ContractModel):
    original_url: str
    canonical_url: str
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    number: int = Field(gt=0)
    kind: ItemKind

    _urls = field_validator("original_url", "canonical_url")(_validate_url)


class RepositoryFacts(ContractModel):
    default_branch: str
    archived: bool
    disabled: bool
    visibility: str
    fork: bool
    html_url: str

    _url = field_validator("html_url")(_validate_url)


class ItemFacts(ContractModel):
    state: Literal["OPEN", "CLOSED"]
    state_reason: str | None
    title: str
    author_login: str | None
    author_association: str | None
    created_at: str
    updated_at: str
    closed_at: str | None
    labels: list[str]
    assignees: list[str]
    locked: bool
    comments_count: int = Field(ge=0)
    draft: bool | None
    merged: bool | None
    merged_at: str | None
    base_ref: str | None
    head_ref: str | None
    base_sha: str | None
    head_sha: str | None
    head_repository_available: bool | None
    mergeable: bool | None
    merge_state_status: str | None

    _dates = field_validator("created_at", "updated_at")(_validate_datetime)

    @field_validator("closed_at", "merged_at")
    @classmethod
    def validate_nullable_date(cls, value: str | None) -> str | None:
        return None if value is None else _validate_datetime(value)


class BranchFacts(ContractModel):
    base_ref: str | None
    head_ref: str | None
    base_sha: str | None
    head_sha: str | None
    ahead_by: int | None = Field(ge=0)
    behind_by: int | None = Field(ge=0)
    compare_status: str | None
    mergeable: bool | None
    merge_state_status: str | None


class CheckSummary(ContractModel):
    failure_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    neutral_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    observed_check_count: int = Field(ge=0)
    collection_complete: bool
    truncated: bool


class NormalizedCheck(ContractModel):
    key: str
    name: str
    provider: Literal["CHECK_RUN", "COMMIT_STATUS"]
    status: CheckStatus
    requiredness: Literal["REQUIRED", "OPTIONAL", "UNKNOWN"]
    details_url: str | None
    updated_at: str
    evidence_id: str

    _date = field_validator("updated_at")(_validate_datetime)

    @field_validator("details_url")
    @classmethod
    def validate_details_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_url(value)


class ChecksFacts(ContractModel):
    items: list[NormalizedCheck] | None
    requiredness_known: bool
    summary: CheckSummary | None
    summary_evidence_id: str | None


class NormalizedReview(ContractModel):
    reviewer_login: str
    state: ReviewState
    submitted_at: str | None
    author_association: str | None
    dismissed: bool
    html_url: str | None
    evidence_id: str

    @field_validator("submitted_at")
    @classmethod
    def validate_submitted_at(cls, value: str | None) -> str | None:
        return None if value is None else _validate_datetime(value)

    @field_validator("html_url")
    @classmethod
    def validate_html_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_url(value)


class ReviewsFacts(ContractModel):
    review_decision: ReviewDecision | None
    review_decision_evidence_id: str | None
    rest_review_history_complete: bool
    latest_review_per_reviewer: list[NormalizedReview] | None
    approved_reviewers: list[str] | None
    changes_requested_reviewers: list[str] | None
    dismissed_reviews: list[NormalizedReview] | None
    unresolved_thread_count: int | None = Field(ge=0)
    unresolved_threads_available: bool
    unresolved_threads_complete: bool
    unresolved_threads_evidence_id: str | None


class ActivityFacts(ContractModel):
    last_author_activity_at: str | None
    last_maintainer_activity_at: str | None
    last_review_activity_at: str | None
    last_commit_at: str | None

    @field_validator(
        "last_author_activity_at", "last_maintainer_activity_at", "last_review_activity_at", "last_commit_at"
    )
    @classmethod
    def validate_activity_date(cls, value: str | None) -> str | None:
        return None if value is None else _validate_datetime(value)


class LinkedItem(ContractModel):
    owner: str
    repo: str
    number: int = Field(gt=0)
    url: str
    state: Literal["OPEN", "CLOSED"] | None
    merged: bool | None
    evidence_id: str

    _url = field_validator("url")(_validate_url)


class LinkedCommit(ContractModel):
    sha: str
    url: str
    evidence_id: str

    _url = field_validator("url")(_validate_url)


class LinksFacts(ContractModel):
    linked_issues: list[LinkedItem] | None
    linked_pull_requests: list[LinkedItem] | None
    linked_commits: list[LinkedCommit] | None
    closing_pull_requests: list[LinkedItem] | None
    explicit_duplicate_labels: list[str]


class AvailabilityFacts(ContractModel):
    rest: SourceAvailability
    graphql: SourceAvailability
    branch_comparison: SourceAvailability
    check_runs: SourceAvailability
    commit_statuses: SourceAvailability
    pull_request_commits: SourceAvailability
    pull_request_reviews: SourceAvailability
    review_threads: SourceAvailability
    comments: SourceAvailability
    rate_limit_remaining: int | None = Field(ge=0)


class NormalizedGitHubFacts(ContractModel):
    schema_version: Literal["1.0.0"]
    fetched_at: str
    source: Source
    repository: RepositoryFacts
    item: ItemFacts
    branches: BranchFacts
    checks: ChecksFacts
    reviews: ReviewsFacts
    activity: ActivityFacts
    links: LinksFacts
    availability: AvailabilityFacts
    evidence: list[EvidenceItem]
    limitations: list[str]

    _fetched_at = field_validator("fetched_at")(_validate_datetime)

    @model_validator(mode="after")
    def validate_contract_invariants(self) -> NormalizedGitHubFacts:
        ids = [item.id for item in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate evidence id")
        if not self.reviews.unresolved_threads_available and (
            self.reviews.unresolved_threads_complete or self.reviews.unresolved_thread_count is not None
        ):
            raise ValueError("unavailable review threads must be incomplete with a null count")

        summary = self.checks.summary
        if summary is not None:
            total = (
                summary.failure_count
                + summary.pending_count
                + summary.success_count
                + summary.skipped_count
                + summary.neutral_count
                + summary.cancelled_count
                + summary.unknown_count
            )
            if total != summary.observed_check_count:
                raise ValueError("check summary counts must equal observedCheckCount")
            if not self.checks.summary_evidence_id or self.checks.summary_evidence_id not in ids:
                raise ValueError("check summary must reference evidence")
            if self.checks.items is None:
                raise ValueError("check summary requires observed check items")
            counts = {
                status: 0 for status in ("FAILURE", "PENDING", "SUCCESS", "SKIPPED", "NEUTRAL", "CANCELLED", "UNKNOWN")
            }
            for check in self.checks.items:
                counts[check.status] += 1
            pairs = {
                "failure_count": "FAILURE",
                "pending_count": "PENDING",
                "success_count": "SUCCESS",
                "skipped_count": "SKIPPED",
                "neutral_count": "NEUTRAL",
                "cancelled_count": "CANCELLED",
                "unknown_count": "UNKNOWN",
            }
            for field_name, status in pairs.items():
                if getattr(summary, field_name) != counts[status]:
                    raise ValueError(f"{field_name} must match check items")
            expected_complete = (
                self.availability.check_runs == "AVAILABLE" and self.availability.commit_statuses == "AVAILABLE"
            )
            expected_truncated = (
                self.availability.check_runs == "TRUNCATED" or self.availability.commit_statuses == "TRUNCATED"
            )
            if summary.collection_complete != expected_complete:
                raise ValueError("collectionComplete must match source availability")
            if summary.truncated != expected_truncated:
                raise ValueError("truncated must match source availability")
        elif self.checks.summary_evidence_id is not None:
            raise ValueError("missing check summary cannot reference evidence")
        elif self.checks.items is not None:
            raise ValueError("observed check items require a summary")

        if self.source.kind == "ISSUE":
            if self.checks.items is not None or self.checks.summary is not None:
                raise ValueError("PR-only checks must be null for issues")
            pr_only = (
                self.availability.branch_comparison,
                self.availability.check_runs,
                self.availability.commit_statuses,
                self.availability.pull_request_commits,
                self.availability.pull_request_reviews,
                self.availability.review_threads,
            )
            if any(state != "NOT_APPLICABLE" for state in pr_only):
                raise ValueError("PR-only sources must be NOT_APPLICABLE for issues")
        return self


def facts_to_dict(facts: NormalizedGitHubFacts) -> dict[str, object]:
    return facts.model_dump(by_alias=True, mode="json")
