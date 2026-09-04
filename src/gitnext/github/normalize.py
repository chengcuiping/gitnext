"""Normalize bounded raw GitHub responses into the frozen v1 facts contract."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Literal, cast
from urllib.parse import quote, urlsplit

from gitnext.domain.evidence import EvidenceBuilder
from gitnext.domain.facts import (
    FACTS_SCHEMA_VERSION,
    CheckStatus,
    NormalizedCheck,
    NormalizedGitHubFacts,
    NormalizedReview,
    ReviewDecision,
    ReviewState,
    SourceAvailability,
)
from gitnext.github.errors import GitHubAccessError
from gitnext.github.raw import OptionalRawSource, RawGitHubData

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
DUPLICATE_LABELS = {"duplicate", "status: duplicate", "type: duplicate"}
AVAILABILITIES = {"AVAILABLE", "NOT_APPLICABLE", "UNAVAILABLE", "RATE_LIMITED", "FORBIDDEN", "TRUNCATED"}


def _as_iso(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _required_iso(value: Any, field: str) -> str:
    normalized = _as_iso(value)
    if normalized is None:
        raise GitHubAccessError("INVALID_RESPONSE", f"GitHub returned an invalid required timestamp for {field}")
    return normalized


def _latest(values: Iterable[str | None]) -> str | None:
    candidates = sorted(value for value in values if value is not None)
    return candidates[-1] if candidates else None


def _url(value: Any, *, nullable: bool = False, empty: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if value == "" and empty:
        return ""
    if not isinstance(value, str):
        raise ValueError("invalid URL")
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid URL")
    return value


def _is_int(value: Any, *, positive: bool = False, nonnegative: bool = False) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return (not positive or value > 0) and (not nonnegative or value >= 0)


def _user(value: Any, *, nullable: bool = True) -> dict[str, Any] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("login"), str):
        raise ValueError("invalid user")
    return value


def _parse_repository(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("invalid repository")
    if not isinstance(value.get("default_branch"), str):
        raise ValueError("invalid repository default_branch")
    for field in ("archived", "disabled", "fork"):
        if not isinstance(value.get(field), bool):
            raise ValueError(f"invalid repository {field}")
    if "visibility" in value and value["visibility"] is not None and not isinstance(value["visibility"], str):
        raise ValueError("invalid repository visibility")
    if "private" in value and value["private"] is not None and not isinstance(value["private"], bool):
        raise ValueError("invalid repository private")
    _url(value.get("html_url"))
    return value


def _parse_common_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("invalid item")
    if value.get("state") not in {"open", "closed"} or not isinstance(value.get("title"), str):
        raise ValueError("invalid item core state")
    if "state_reason" in value and value["state_reason"] is not None and not isinstance(value["state_reason"], str):
        raise ValueError("invalid item state_reason")
    if "user" not in value or "closed_at" not in value:
        raise ValueError("missing required item field")
    _user(value.get("user"))
    if (
        "author_association" in value
        and value["author_association"] is not None
        and not isinstance(value["author_association"], str)
    ):
        raise ValueError("invalid item author_association")
    for field in ("created_at", "updated_at"):
        if not isinstance(value.get(field), str) or _as_iso(value[field]) is None:
            raise ValueError(f"invalid item {field}")
    if value.get("closed_at") is not None and _as_iso(value.get("closed_at")) is None:
        raise ValueError("invalid item closed_at")
    labels = value.get("labels")
    if not isinstance(labels, list):
        raise ValueError("invalid item labels")
    for label in labels:
        if isinstance(label, str):
            continue
        if not isinstance(label, dict) or (label.get("name") is not None and not isinstance(label.get("name"), str)):
            raise ValueError("invalid item label")
    assignees = value.get("assignees", [])
    if assignees is not None:
        if not isinstance(assignees, list):
            raise ValueError("invalid item assignees")
        for assignee in assignees:
            _user(assignee, nullable=False)
    if not isinstance(value.get("locked"), bool) or not _is_int(value.get("comments"), nonnegative=True):
        raise ValueError("invalid item counters")
    _url(value.get("html_url"))
    return value


def _parse_item(value: Any, is_pull_request: bool) -> dict[str, Any]:
    item = _parse_common_item(value)
    if not is_pull_request:
        return item
    if not {"draft", "merged_at", "mergeable"}.issubset(item):
        raise ValueError("missing required pull field")
    if item.get("draft") is not None and not isinstance(item.get("draft"), bool):
        raise ValueError("invalid pull draft")
    if not isinstance(item.get("merged"), bool):
        raise ValueError("invalid pull merged")
    if item.get("merged_at") is not None and _as_iso(item.get("merged_at")) is None:
        raise ValueError("invalid pull merged_at")
    if item.get("mergeable") is not None and not isinstance(item.get("mergeable"), bool):
        raise ValueError("invalid pull mergeable")
    if (
        "mergeable_state" in item
        and item["mergeable_state"] is not None
        and not isinstance(item["mergeable_state"], str)
    ):
        raise ValueError("invalid pull mergeable_state")
    for branch_name in ("base", "head"):
        branch = item.get(branch_name)
        if (
            not isinstance(branch, dict)
            or not isinstance(branch.get("ref"), str)
            or not isinstance(branch.get("sha"), str)
        ):
            raise ValueError(f"invalid pull {branch_name}")
    if "repo" not in item["head"]:
        raise ValueError("invalid pull head repository")
    return item


def _labels_from(raw: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for label in raw["labels"]:
        candidate = label if isinstance(label, str) else label.get("name")
        if candidate and candidate not in labels:
            labels.append(candidate)
    return labels


def _normalize_check_run_status(status: str, conclusion: str | None) -> CheckStatus:
    if status != "completed":
        return "PENDING" if status in {"queued", "in_progress", "waiting", "requested", "pending"} else "UNKNOWN"
    if conclusion == "success":
        return "SUCCESS"
    if conclusion in {"failure", "timed_out", "action_required", "startup_failure", "stale"}:
        return "FAILURE"
    if conclusion == "neutral":
        return "NEUTRAL"
    if conclusion == "cancelled":
        return "CANCELLED"
    if conclusion == "skipped":
        return "SKIPPED"
    return "UNKNOWN"


def _normalize_commit_status(state: str) -> CheckStatus:
    if state == "success":
        return "SUCCESS"
    if state in {"failure", "error"}:
        return "FAILURE"
    if state in {"pending", "expected"}:
        return "PENDING"
    return "UNKNOWN"


def _normalize_review_state(state: str) -> ReviewState:
    normalized = state.upper()
    if normalized in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"}:
        return cast(ReviewState, normalized)
    return "UNKNOWN"


def _normalize_review_decision(value: str | None) -> ReviewDecision | None:
    if value is None:
        return None
    normalized = value.upper()
    if normalized in {"APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"}:
        return cast(ReviewDecision, normalized)
    return "UNKNOWN"


def _safe_key(value: str) -> str:
    return quote(value.lower(), safe="~()*!.'-_")


def _javascript_number(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _source_availability(source: OptionalRawSource, applicable: bool = True) -> SourceAvailability:
    if not applicable:
        return "NOT_APPLICABLE"
    if source.availability in AVAILABILITIES:
        return source.availability
    if source.available:
        return "TRUNCATED" if source.truncated else "AVAILABLE"
    return "UNAVAILABLE"


def _append_source_limitation(limitations: list[str], source: OptionalRawSource, applicable: bool = True) -> None:
    availability = _source_availability(source, applicable)
    if availability == "NOT_APPLICABLE":
        return
    if source.limitation:
        limitations.append(source.limitation)
    if source.truncated and not source.limitation:
        limitations.append("A GitHub collection was truncated at its safety limit.")


def _connection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("nodes"), list):
        raise ValueError("invalid GraphQL connection")
    page_info = value.get("pageInfo")
    if not isinstance(page_info, dict) or not isinstance(page_info.get("hasNextPage"), bool):
        raise ValueError("invalid GraphQL pageInfo")
    for node in value["nodes"]:
        if node is None:
            continue
        if not isinstance(node, dict) or "repository" not in node or not _is_int(node.get("number"), positive=True):
            raise ValueError("invalid linked node")
        _url(node.get("url"))
        if not isinstance(node.get("state"), str):
            raise ValueError("invalid linked state")
        if "merged" in node and node["merged"] is not None and not isinstance(node["merged"], bool):
            raise ValueError("invalid linked merged")
        repository = node.get("repository")
        if repository is not None and (
            not isinstance(repository, dict) or not isinstance(repository.get("nameWithOwner"), str)
        ):
            raise ValueError("invalid linked repository")
    return value


def _parse_graphql(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("invalid GraphQL response")
    repository = value.get("repository")
    if repository is None:
        return value
    if not isinstance(repository, dict):
        raise ValueError("invalid GraphQL repository")
    pull = repository.get("pullRequest")
    if pull is not None:
        if not isinstance(pull, dict):
            raise ValueError("invalid GraphQL pull request")
        if "reviewDecision" not in pull:
            raise ValueError("missing GraphQL reviewDecision")
        decision = pull.get("reviewDecision")
        if decision is not None and not isinstance(decision, str):
            raise ValueError("invalid GraphQL reviewDecision")
        threads = pull.get("reviewThreads")
        if not isinstance(threads, dict) or not isinstance(threads.get("nodes"), list):
            raise ValueError("invalid GraphQL reviewThreads")
        page_info = threads.get("pageInfo")
        if not isinstance(page_info, dict) or not isinstance(page_info.get("hasNextPage"), bool):
            raise ValueError("invalid GraphQL reviewThreads pageInfo")
        for thread in threads["nodes"]:
            if thread is not None and (
                not isinstance(thread, dict)
                or not isinstance(thread.get("id"), str)
                or not isinstance(thread.get("isResolved"), bool)
            ):
                raise ValueError("invalid GraphQL review thread")
        _connection(pull.get("closingIssuesReferences"))
    issue = repository.get("issue")
    if issue is not None:
        if not isinstance(issue, dict):
            raise ValueError("invalid GraphQL issue")
        _connection(issue.get("closedByPullRequestsReferences"))
    return value


def _parse_linked(
    nodes: list[Any],
    fallback_owner: str,
    fallback_repo: str,
    evidence: EvidenceBuilder,
    category: Literal["issue", "pull"],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in nodes:
        if node is None:
            continue
        repository = node.get("repository")
        parts = repository["nameWithOwner"].split("/") if repository else []
        owner = parts[0] if parts and parts[0] else fallback_owner
        repo = parts[1] if len(parts) > 1 and parts[1] else fallback_repo
        linked_key = f"{owner}/{repo}#{node['number']}"
        evidence_id = f"link.{category}.{_safe_key(linked_key)}"
        state = node["state"].upper()
        merged = node.get("merged")
        evidence.add(
            evidence_id,
            "links",
            f"GitHub explicitly linked {category} {owner}/{repo}#{node['number']}",
            {"state": state, "merged": merged},
            "GraphQL.issue.closedByPullRequestsReferences"
            if category == "pull"
            else "GraphQL.pullRequest.closingIssuesReferences",
            node["url"],
        )
        result.append(
            {
                "owner": owner,
                "repo": repo,
                "number": node["number"],
                "url": node["url"],
                "state": state if state in {"OPEN", "CLOSED"} else None,
                "merged": merged,
                "evidenceId": evidence_id,
            }
        )
    return result


def _raw_input(raw: RawGitHubData | dict[str, Any]) -> RawGitHubData:
    if isinstance(raw, RawGitHubData):
        return raw
    return RawGitHubData.from_dict(raw)


def normalize_github_data(raw_input: RawGitHubData | dict[str, Any]) -> NormalizedGitHubFacts:
    raw = _raw_input(raw_input)
    is_pull_request = raw.source.kind == "PULL_REQUEST"
    try:
        repo = _parse_repository(raw.repository)
        input_item = _parse_item(raw.item, is_pull_request)
    except (KeyError, TypeError, ValueError) as error:
        raise GitHubAccessError(
            "INVALID_RESPONSE", "GitHub returned a response that does not match the expected schema"
        ) from error
    pull = input_item if is_pull_request else None
    pull_merge_state = cast(str | None, pull.get("mergeable_state")) if pull is not None else None
    observed_at = _as_iso(raw.fetched_at)
    if observed_at is None:
        raise GitHubAccessError("INVALID_RESPONSE", "Invalid fetchedAt timestamp")
    evidence = EvidenceBuilder(observed_at, raw.source.canonical_url)
    limitations = list(raw.limitations)
    _append_source_limitation(limitations, raw.compare, is_pull_request)
    _append_source_limitation(limitations, raw.check_runs, is_pull_request)
    _append_source_limitation(limitations, raw.commit_statuses, is_pull_request)
    _append_source_limitation(limitations, raw.reviews, is_pull_request)
    _append_source_limitation(limitations, raw.commits, is_pull_request)
    _append_source_limitation(limitations, raw.comments)
    _append_source_limitation(limitations, raw.graphql)

    evidence.add("item.state", "item", "GitHub item state", input_item["state"].upper(), "REST.item.state")
    if "state_reason" in input_item:
        evidence.add(
            "item.stateReason",
            "item",
            "GitHub item state reason",
            input_item.get("state_reason"),
            "REST.item.state_reason",
        )
    evidence.add(
        "repository.archived",
        "repository",
        "Repository archived state",
        repo["archived"],
        "REST.repository.archived",
        repo["html_url"],
    )
    evidence.add(
        "repository.disabled",
        "repository",
        "Repository disabled state",
        repo["disabled"],
        "REST.repository.disabled",
        repo["html_url"],
    )
    labels = _labels_from(input_item)
    for label in labels:
        canonical = re.sub(r"\s+", " ", label.strip().lower())
        evidence_id = f"label.{_safe_key(canonical)}"
        if not any(item.id == evidence_id for item in evidence.values()):
            evidence.add(evidence_id, "label", f"GitHub label: {label}", label, "REST.item.labels")
    assignees = [user["login"] for user in (input_item.get("assignees") or [])]
    evidence.add("item.assignees", "item", "GitHub item assignees", assignees, "REST.item.assignees")
    if pull is not None:
        evidence.add("item.merged", "item", "Pull request merged state", pull["merged"], "REST.pull.merged")
        evidence.add("item.draft", "item", "Pull request draft state", pull["draft"], "REST.pull.draft")
        evidence.add(
            "branches.mergeable", "branches", "GitHub computed mergeability", pull["mergeable"], "REST.pull.mergeable"
        )
        evidence.add(
            "branches.mergeStateStatus",
            "branches",
            "GitHub merge state status",
            pull_merge_state.upper() if pull_merge_state else None,
            "REST.pull.mergeable_state",
        )

    ahead_by: int | None = None
    behind_by: int | None = None
    compare_status: str | None = None
    branch_comparison_availability = _source_availability(raw.compare, is_pull_request)
    if is_pull_request and raw.compare.available:
        candidate = raw.compare.data
        if (
            isinstance(candidate, dict)
            and isinstance(candidate.get("status"), str)
            and _is_int(candidate.get("ahead_by"), nonnegative=True)
            and _is_int(candidate.get("behind_by"), nonnegative=True)
        ):
            ahead_by = candidate["ahead_by"]
            behind_by = candidate["behind_by"]
            compare_status = candidate["status"].upper()
            evidence.add(
                "branches.compare",
                "branches",
                "GitHub branch comparison",
                {"aheadBy": ahead_by, "behindBy": behind_by, "compareStatus": compare_status},
                "REST.compare",
            )
        else:
            branch_comparison_availability = "UNAVAILABLE"
            limitations.append("Compare response failed schema validation.")

    checks_by_key: dict[str, tuple[NormalizedCheck, str]] = {}
    check_runs_valid = False
    commit_statuses_valid = False
    check_runs_availability = _source_availability(raw.check_runs, is_pull_request)
    commit_statuses_availability = _source_availability(raw.commit_statuses, is_pull_request)
    if is_pull_request and raw.check_runs.available:
        candidate = raw.check_runs.data
        valid = isinstance(candidate, dict) and isinstance(candidate.get("check_runs"), list)
        parsed_runs: list[dict[str, Any]] = []
        if valid:
            for run in candidate["check_runs"]:
                try:
                    if (
                        not isinstance(run, dict)
                        or not {"conclusion", "details_url", "app"}.issubset(run)
                        or not isinstance(run.get("id"), (int, float))
                        or isinstance(run.get("id"), bool)
                    ):
                        raise ValueError
                    if not isinstance(run.get("name"), str) or not isinstance(run.get("status"), str):
                        raise ValueError
                    if run.get("conclusion") is not None and not isinstance(run.get("conclusion"), str):
                        raise ValueError
                    _url(run.get("details_url"), nullable=True)
                    for date_field in ("started_at", "completed_at"):
                        if run.get(date_field) is not None and _as_iso(run.get(date_field)) is None:
                            raise ValueError
                    if (
                        "run_attempt" in run
                        and run["run_attempt"] is not None
                        and not _is_int(run["run_attempt"], positive=True)
                    ):
                        raise ValueError
                    app = run.get("app")
                    if app is not None and (
                        not isinstance(app, dict)
                        or (app.get("slug") is not None and not isinstance(app.get("slug"), str))
                    ):
                        raise ValueError
                    parsed_runs.append(run)
                except ValueError:
                    valid = False
                    break
        if not valid:
            check_runs_availability = "UNAVAILABLE"
            limitations.append("Check runs response failed schema validation.")
        else:
            check_runs_valid = True
            for run in parsed_runs:
                app = run.get("app")
                slug = app.get("slug") if app else None
                provider = "unknown-app" if slug is None else slug
                key = f"check-run:{provider}:{run['name']}"
                updated_at = _as_iso(
                    run.get("completed_at") if run.get("completed_at") is not None else run.get("started_at")
                )
                if updated_at is None:
                    limitations.append(f"Check run {run['name']} omitted because it has no observable timestamp.")
                    continue
                attempt = run.get("run_attempt", 1)
                order = f"{attempt:010d}:{updated_at}:{_javascript_number(run['id']).rjust(20, '0')}"
                evidence_id = f"check.{_safe_key(key)}.status"
                check = NormalizedCheck.model_validate(
                    {
                        "key": key,
                        "name": run["name"],
                        "provider": "CHECK_RUN",
                        "status": _normalize_check_run_status(run["status"], run.get("conclusion")),
                        "requiredness": "UNKNOWN",
                        "detailsUrl": run.get("details_url"),
                        "updatedAt": updated_at,
                        "evidenceId": evidence_id,
                    }
                )
                existing_check = checks_by_key.get(key)
                if existing_check is None or order > existing_check[1]:
                    checks_by_key[key] = (check, order)

    if is_pull_request and raw.commit_statuses.available:
        candidate = raw.commit_statuses.data
        valid = isinstance(candidate, list)
        parsed_statuses: list[dict[str, Any]] = []
        if valid:
            for status in candidate:
                try:
                    if (
                        not isinstance(status, dict)
                        or "target_url" not in status
                        or not isinstance(status.get("id"), (int, float))
                        or isinstance(status.get("id"), bool)
                    ):
                        raise ValueError
                    if not isinstance(status.get("context"), str) or not isinstance(status.get("state"), str):
                        raise ValueError
                    _url(status.get("target_url"), nullable=True, empty=True)
                    if _as_iso(status.get("updated_at")) is None or _as_iso(status.get("created_at")) is None:
                        raise ValueError
                    parsed_statuses.append(status)
                except ValueError:
                    valid = False
                    break
        if not valid:
            commit_statuses_availability = "UNAVAILABLE"
            limitations.append("Commit statuses response failed schema validation.")
        else:
            commit_statuses_valid = True
            for status in parsed_statuses:
                key = f"commit-status:{status['context']}"
                updated_at = _required_iso(status["updated_at"], "commit status updated_at")
                order = f"{updated_at}:{_javascript_number(status['id']).rjust(20, '0')}"
                evidence_id = f"check.{_safe_key(key)}.status"
                check = NormalizedCheck.model_validate(
                    {
                        "key": key,
                        "name": status["context"],
                        "provider": "COMMIT_STATUS",
                        "status": _normalize_commit_status(status["state"]),
                        "requiredness": "UNKNOWN",
                        "detailsUrl": status.get("target_url") or None,
                        "updatedAt": updated_at,
                        "evidenceId": evidence_id,
                    }
                )
                existing_check = checks_by_key.get(key)
                if existing_check is None or order > existing_check[1]:
                    checks_by_key[key] = (check, order)

    check_items = [value[0] for _, value in sorted(checks_by_key.items())]
    for check in check_items:
        evidence.add(
            check.evidence_id,
            "check",
            f"Latest status for {check.key}",
            check.status,
            "REST.check_runs" if check.provider == "CHECK_RUN" else "REST.commit_statuses",
            check.details_url or raw.source.canonical_url,
        )
    checks_available = check_runs_valid or commit_statuses_valid
    check_summary: dict[str, Any] | None = None
    if checks_available:
        check_summary = {
            "failureCount": sum(check.status == "FAILURE" for check in check_items),
            "pendingCount": sum(check.status == "PENDING" for check in check_items),
            "successCount": sum(check.status == "SUCCESS" for check in check_items),
            "skippedCount": sum(check.status == "SKIPPED" for check in check_items),
            "neutralCount": sum(check.status == "NEUTRAL" for check in check_items),
            "cancelledCount": sum(check.status == "CANCELLED" for check in check_items),
            "unknownCount": sum(check.status == "UNKNOWN" for check in check_items),
            "observedCheckCount": len(check_items),
            "collectionComplete": check_runs_availability == "AVAILABLE"
            and commit_statuses_availability == "AVAILABLE",
            "truncated": check_runs_availability == "TRUNCATED" or commit_statuses_availability == "TRUNCATED",
        }
    check_summary_evidence_id = "checks.summary" if check_summary is not None else None
    if check_summary is not None:
        evidence.add(
            "checks.summary",
            "check_summary",
            "Summary of latest observed checks and collection completeness",
            check_summary,
            "GitNext.normalization.checkSummary",
        )
    if pull is not None:
        limitations.append("Required check configuration is unknown.")

    latest_review_map: dict[str, tuple[NormalizedReview, int | float, str]] = {}
    dismissed_reviews: list[NormalizedReview] = []
    review_activity: list[str] = []
    reviews_available = False
    rest_review_history_complete = False
    pull_request_reviews_availability = _source_availability(raw.reviews, is_pull_request)
    if is_pull_request and raw.reviews.available:
        candidate = raw.reviews.data
        valid = isinstance(candidate, list)
        parsed_reviews: list[dict[str, Any]] = []
        if valid:
            for review in candidate:
                try:
                    if (
                        not isinstance(review, dict)
                        or not {"submitted_at", "user"}.issubset(review)
                        or not isinstance(review.get("id"), (int, float))
                        or isinstance(review.get("id"), bool)
                    ):
                        raise ValueError
                    if not isinstance(review.get("state"), str):
                        raise ValueError
                    if review.get("submitted_at") is not None and _as_iso(review.get("submitted_at")) is None:
                        raise ValueError
                    _url(review.get("html_url"), nullable=True)
                    _user(review.get("user"))
                    if (
                        "author_association" in review
                        and review["author_association"] is not None
                        and not isinstance(review["author_association"], str)
                    ):
                        raise ValueError
                    parsed_reviews.append(review)
                except ValueError:
                    valid = False
                    break
        if not valid:
            pull_request_reviews_availability = "UNAVAILABLE"
            limitations.append("Reviews response failed schema validation.")
        else:
            reviews_available = True
            rest_review_history_complete = not raw.reviews.truncated
            for index, review in enumerate(parsed_reviews):
                if review.get("user") is None:
                    continue
                login = review["user"]["login"]
                submitted_at = _as_iso(review.get("submitted_at"))
                if submitted_at:
                    review_activity.append(submitted_at)
                state = _normalize_review_state(review["state"])
                dismissed = state == "DISMISSED"
                evidence_id = (
                    f"review.dismissed.{_javascript_number(review['id'])}"
                    if dismissed
                    else f"review.{_safe_key(login)}.latest"
                )
                normalized_review = NormalizedReview.model_validate(
                    {
                        "reviewerLogin": login,
                        "state": state,
                        "submittedAt": submitted_at,
                        "authorAssociation": review.get("author_association"),
                        "dismissed": dismissed,
                        "htmlUrl": review.get("html_url"),
                        "evidenceId": evidence_id,
                    }
                )
                if dismissed:
                    evidence.add(
                        evidence_id,
                        "review",
                        f"Dismissed review by {login}",
                        "DISMISSED",
                        "REST.pull.reviews",
                        review.get("html_url") or raw.source.canonical_url,
                    )
                    dismissed_reviews.append(normalized_review)
                    current = latest_review_map.get(login)
                    if current is not None and current[1] == review["id"]:
                        del latest_review_map[login]
                else:
                    order = f"{submitted_at or ''}:{index:010d}"
                    existing_review = latest_review_map.get(login)
                    decisive = state in {"APPROVED", "CHANGES_REQUESTED"}
                    may_replace = (
                        existing_review is None
                        or decisive
                        or (
                            existing_review[0].state not in {"APPROVED", "CHANGES_REQUESTED"}
                            and order > existing_review[2]
                        )
                    )
                    if may_replace:
                        latest_review_map[login] = (normalized_review, review["id"], order)
                    if state in {"UNKNOWN", "PENDING"}:
                        rest_review_history_complete = False
                        limitations.append(
                            f"REST review {_javascript_number(review['id'])} has a non-decisive {state} state; "
                            "effective review reconstruction is conservative."
                        )
    latest_reviews = [value[0] for _, value in sorted(latest_review_map.items())]
    for review in latest_reviews:
        evidence.add(
            review.evidence_id,
            "review",
            f"Latest effective review by {review.reviewer_login}",
            review.state,
            "REST.pull.reviews",
            review.html_url or raw.source.canonical_url,
        )

    review_decision: ReviewDecision | None = None
    review_decision_evidence_id: str | None = None
    unresolved_thread_count: int | None = None
    unresolved_threads_available = False
    unresolved_threads_complete = False
    unresolved_threads_evidence_id: str | None = None
    graphql_available = False
    graphql_availability = _source_availability(raw.graphql)
    review_threads_availability: SourceAvailability = graphql_availability if is_pull_request else "NOT_APPLICABLE"
    linked_issues: list[dict[str, Any]] | None = None
    linked_pull_requests: list[dict[str, Any]] | None = None
    closing_pull_requests: list[dict[str, Any]] | None = None
    if raw.graphql.available:
        try:
            parsed_graphql = _parse_graphql(raw.graphql.data)
            graphql_repository = parsed_graphql.get("repository")
            if graphql_repository is None:
                raise ValueError("missing GraphQL repository")
        except (AttributeError, KeyError, TypeError, ValueError):
            graphql_availability = "UNAVAILABLE"
            if is_pull_request:
                review_threads_availability = "UNAVAILABLE"
            limitations.append("GraphQL response failed schema validation.")
        else:
            gql_pull = graphql_repository.get("pullRequest")
            gql_issue = graphql_repository.get("issue")
            if is_pull_request and gql_pull is not None:
                graphql_available = True
                review_decision = _normalize_review_decision(gql_pull.get("reviewDecision"))
                review_decision_evidence_id = "reviews.reviewDecision"
                evidence.add(
                    review_decision_evidence_id,
                    "review",
                    "GitHub aggregate pull request review decision",
                    review_decision,
                    "GraphQL.pullRequest.reviewDecision",
                )
                if review_decision == "UNKNOWN":
                    raw_value = gql_pull.get("reviewDecision")
                    limitations.append(
                        f"Unknown GraphQL reviewDecision value: {raw_value if raw_value is not None else 'null'}."
                    )
                threads = gql_pull["reviewThreads"]
                unresolved_thread_count = sum(
                    thread is not None and not thread["isResolved"] for thread in threads["nodes"]
                )
                unresolved_threads_available = True
                unresolved_threads_complete = not threads["pageInfo"]["hasNextPage"]
                review_threads_availability = "AVAILABLE" if unresolved_threads_complete else "TRUNCATED"
                unresolved_threads_evidence_id = "reviews.unresolvedThreadCount"
                evidence.add(
                    unresolved_threads_evidence_id,
                    "review_thread",
                    "Known unresolved review thread count",
                    {"count": unresolved_thread_count, "complete": unresolved_threads_complete},
                    "GraphQL.pullRequest.reviewThreads",
                )
                closing = gql_pull["closingIssuesReferences"]
                linked_issues = _parse_linked(closing["nodes"], raw.source.owner, raw.source.repo, evidence, "issue")
                if not unresolved_threads_complete:
                    limitations.append(
                        "Review threads are incomplete because GraphQL hasNextPage=true; "
                        "count covers only the fetched page."
                    )
                if closing["pageInfo"]["hasNextPage"]:
                    limitations.append("Closing issue links were truncated at 100 records.")
            elif not is_pull_request and gql_issue is not None:
                graphql_available = True
                closed_by = gql_issue["closedByPullRequestsReferences"]
                pulls = _parse_linked(closed_by["nodes"], raw.source.owner, raw.source.repo, evidence, "pull")
                closing_pull_requests = pulls
                linked_pull_requests = pulls
                if closed_by["pageInfo"]["hasNextPage"]:
                    limitations.append("Closing pull request links were truncated at 100 records.")
            else:
                graphql_availability = "UNAVAILABLE"
                if is_pull_request:
                    review_threads_availability = "UNAVAILABLE"
                limitations.append("GraphQL response did not contain the requested item.")
    if is_pull_request and not unresolved_threads_available:
        limitations.append("Unresolved review threads are unknown.")
    has_rest_changes = any(review.state == "CHANGES_REQUESTED" for review in latest_reviews)
    has_rest_approval = any(review.state == "APPROVED" for review in latest_reviews)
    review_conflict = (review_decision == "CHANGES_REQUESTED" and has_rest_approval and not has_rest_changes) or (
        review_decision in {"APPROVED", "REVIEW_REQUIRED"} and has_rest_changes
    )
    if graphql_available and reviews_available and review_conflict:
        limitations.append(
            "GraphQL reviewDecision conflicts with the effective REST review state; GraphQL controls the verdict."
        )

    author_login = input_item.get("user", {}).get("login") if input_item.get("user") else None
    author_activity = [_required_iso(input_item["created_at"], "item.created_at")]
    maintainer_activity: list[str] = []
    comments_valid = False
    if raw.comments.available:
        candidate = raw.comments.data
        valid = isinstance(candidate, list)
        parsed_comments: list[dict[str, Any]] = []
        if valid:
            for comment in candidate:
                try:
                    if not isinstance(comment, dict):
                        raise ValueError
                    _user(comment.get("user"))
                    if (
                        "author_association" in comment
                        and comment["author_association"] is not None
                        and not isinstance(comment["author_association"], str)
                    ):
                        raise ValueError
                    if _as_iso(comment.get("created_at")) is None or _as_iso(comment.get("updated_at")) is None:
                        raise ValueError
                    parsed_comments.append(comment)
                except ValueError:
                    valid = False
                    break
        if not valid:
            limitations.append("Comments response failed schema validation.")
        else:
            comments_valid = True
            for comment in parsed_comments:
                activity_time = _as_iso(comment.get("updated_at")) or _as_iso(comment.get("created_at"))
                if activity_time is None:
                    continue
                if comment.get("user") and comment["user"]["login"] == author_login:
                    author_activity.append(activity_time)
                if comment.get("author_association") in MAINTAINER_ASSOCIATIONS:
                    maintainer_activity.append(activity_time)
    for review in latest_reviews:
        if review.author_association in MAINTAINER_ASSOCIATIONS and review.submitted_at:
            maintainer_activity.append(review.submitted_at)

    linked_commits: list[dict[str, Any]] | None = None
    last_commit_at: str | None = None
    pull_request_commits_availability = _source_availability(raw.commits, is_pull_request)
    if is_pull_request and raw.commits.available:
        candidate = raw.commits.data
        valid = isinstance(candidate, list)
        parsed_commits: list[dict[str, Any]] = []
        if valid:
            for commit in candidate:
                try:
                    if not isinstance(commit, dict) or not isinstance(commit.get("sha"), str):
                        raise ValueError
                    _url(commit.get("html_url"))
                    if "author" in commit:
                        _user(commit.get("author"))
                    commit_data = commit.get("commit")
                    if not isinstance(commit_data, dict):
                        raise ValueError
                    if not {"author", "committer"}.issubset(commit_data):
                        raise ValueError
                    for actor in ("author", "committer"):
                        actor_data = commit_data.get(actor)
                        if actor_data is not None:
                            if not isinstance(actor_data, dict):
                                raise ValueError
                            if "date" not in actor_data:
                                raise ValueError
                            if actor_data.get("date") is not None and _as_iso(actor_data.get("date")) is None:
                                raise ValueError
                    parsed_commits.append(commit)
                except ValueError:
                    valid = False
                    break
        if not valid:
            pull_request_commits_availability = "UNAVAILABLE"
            limitations.append("Commits response failed schema validation.")
        else:
            linked_commits = []
            commit_dates: list[str | None] = []
            for commit in parsed_commits:
                evidence_id = f"commit.{_safe_key(commit['sha'])}"
                evidence.add(
                    evidence_id,
                    "commit",
                    f"Commit explicitly present in pull request: {commit['sha']}",
                    commit["sha"],
                    "REST.pull.commits",
                    commit["html_url"],
                )
                linked_commits.append({"sha": commit["sha"], "url": commit["html_url"], "evidenceId": evidence_id})
                commit_data = commit["commit"]
                committer = commit_data.get("committer")
                author = commit_data.get("author")
                commit_dates.append(
                    _as_iso(committer.get("date") if committer else None)
                    or _as_iso(author.get("date") if author else None)
                )
            last_commit_at = _latest(commit_dates)

    comments_availability = _source_availability(raw.comments)
    if raw.comments.available and not comments_valid:
        comments_availability = "UNAVAILABLE"

    facts = {
        "schemaVersion": FACTS_SCHEMA_VERSION,
        "fetchedAt": observed_at,
        "source": raw.source.model_dump(by_alias=True, mode="json"),
        "repository": {
            "defaultBranch": repo["default_branch"],
            "archived": repo["archived"],
            "disabled": repo["disabled"],
            "visibility": repo.get("visibility")
            if repo.get("visibility") is not None
            else ("private" if repo.get("private") else "public"),
            "fork": repo["fork"],
            "htmlUrl": repo["html_url"],
        },
        "item": {
            "state": "OPEN" if input_item["state"] == "open" else "CLOSED",
            "stateReason": input_item.get("state_reason"),
            "title": input_item["title"],
            "authorLogin": author_login,
            "authorAssociation": input_item.get("author_association"),
            "createdAt": _required_iso(input_item["created_at"], "item.created_at"),
            "updatedAt": _required_iso(input_item["updated_at"], "item.updated_at"),
            "closedAt": _as_iso(input_item.get("closed_at")),
            "labels": labels,
            "assignees": assignees,
            "locked": input_item["locked"],
            "commentsCount": input_item["comments"],
            "draft": pull.get("draft") if pull else None,
            "merged": pull.get("merged") if pull else None,
            "mergedAt": _as_iso(pull.get("merged_at")) if pull else None,
            "baseRef": pull["base"]["ref"] if pull else None,
            "headRef": pull["head"]["ref"] if pull else None,
            "baseSha": pull["base"]["sha"] if pull else None,
            "headSha": pull["head"]["sha"] if pull else None,
            "headRepositoryAvailable": pull["head"]["repo"] is not None if pull else None,
            "mergeable": pull.get("mergeable") if pull else None,
            "mergeStateStatus": pull_merge_state.upper() if pull_merge_state else None,
        },
        "branches": {
            "baseRef": pull["base"]["ref"] if pull else None,
            "headRef": pull["head"]["ref"] if pull else None,
            "baseSha": pull["base"]["sha"] if pull else None,
            "headSha": pull["head"]["sha"] if pull else None,
            "aheadBy": ahead_by,
            "behindBy": behind_by,
            "compareStatus": compare_status,
            "mergeable": pull.get("mergeable") if pull else None,
            "mergeStateStatus": pull_merge_state.upper() if pull_merge_state else None,
        },
        "checks": {
            "items": [item.model_dump(by_alias=True, mode="json") for item in check_items]
            if checks_available
            else None,
            "requirednessKnown": False,
            "summary": check_summary,
            "summaryEvidenceId": check_summary_evidence_id,
        },
        "reviews": {
            "reviewDecision": review_decision,
            "reviewDecisionEvidenceId": review_decision_evidence_id,
            "restReviewHistoryComplete": rest_review_history_complete,
            "latestReviewPerReviewer": [item.model_dump(by_alias=True, mode="json") for item in latest_reviews]
            if reviews_available
            else None,
            "approvedReviewers": [item.reviewer_login for item in latest_reviews if item.state == "APPROVED"]
            if reviews_available
            else None,
            "changesRequestedReviewers": [
                item.reviewer_login for item in latest_reviews if item.state == "CHANGES_REQUESTED"
            ]
            if reviews_available
            else None,
            "dismissedReviews": [item.model_dump(by_alias=True, mode="json") for item in dismissed_reviews]
            if reviews_available
            else None,
            "unresolvedThreadCount": unresolved_thread_count,
            "unresolvedThreadsAvailable": unresolved_threads_available,
            "unresolvedThreadsComplete": unresolved_threads_complete,
            "unresolvedThreadsEvidenceId": unresolved_threads_evidence_id,
        },
        "activity": {
            "lastAuthorActivityAt": _latest(author_activity),
            "lastMaintainerActivityAt": _latest(maintainer_activity),
            "lastReviewActivityAt": _latest([_as_iso(value) for value in review_activity]),
            "lastCommitAt": last_commit_at,
        },
        "links": {
            "linkedIssues": linked_issues,
            "linkedPullRequests": linked_pull_requests,
            "linkedCommits": linked_commits,
            "closingPullRequests": closing_pull_requests,
            "explicitDuplicateLabels": [
                label for label in labels if re.sub(r"\s+", " ", label.strip().lower()) in DUPLICATE_LABELS
            ],
        },
        "availability": {
            "rest": "AVAILABLE",
            "graphql": graphql_availability,
            "branchComparison": branch_comparison_availability,
            "checkRuns": check_runs_availability,
            "commitStatuses": commit_statuses_availability,
            "pullRequestCommits": pull_request_commits_availability,
            "pullRequestReviews": pull_request_reviews_availability,
            "reviewThreads": review_threads_availability,
            "comments": comments_availability,
            "rateLimitRemaining": raw.rate_limit_remaining,
        },
        "evidence": [item.model_dump(by_alias=True, mode="json") for item in evidence.values()],
        "limitations": sorted(set(limitations), key=lambda value: value.encode("utf-16-be", errors="surrogatepass")),
    }
    return NormalizedGitHubFacts.model_validate(facts)
