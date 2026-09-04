"""Bounded, read-only GitHub fact acquisition."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from gitnext.domain.facts import NormalizedGitHubFacts, Source, SourceAvailability
from gitnext.github.errors import classify_github_error
from gitnext.github.graphql_client import GitHubGraphqlReader, ReadOnlyGraphqlClient
from gitnext.github.normalize import normalize_github_data
from gitnext.github.raw import OptionalRawSource, RawGitHubData
from gitnext.github.rest_client import GitHubRestReader, ReadOnlyRestClient, RestResult


class _DefaultGraphql:
    pass


DEFAULT_GRAPHQL = _DefaultGraphql()


@dataclass
class FetchDependencies:
    rest: GitHubRestReader | None = None
    graphql: GitHubGraphqlReader | _DefaultGraphql | None = DEFAULT_GRAPHQL
    now: Callable[[], str] | None = None
    delay: Callable[[int], None] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _wait(milliseconds: int) -> None:
    time.sleep(milliseconds / 1000)


def _unavailable(limitation: str, availability: SourceAvailability = "UNAVAILABLE") -> OptionalRawSource:
    return OptionalRawSource(False, None, availability=availability, limitation=limitation)


def _not_applicable() -> OptionalRawSource:
    return OptionalRawSource(False, None, availability="NOT_APPLICABLE")


def _error_availability(kind: str) -> SourceAvailability:
    if kind == "RATE_LIMIT":
        return "RATE_LIMITED"
    if kind == "FORBIDDEN":
        return "FORBIDDEN"
    return "UNAVAILABLE"


def _optional(request: Callable[[], RestResult], label: str) -> tuple[OptionalRawSource, int | None]:
    try:
        result = request()
        object_data = result.data if isinstance(result.data, dict) else None
        collection = (
            result.data if isinstance(result.data, list) else object_data.get("check_runs") if object_data else None
        )
        collection_size = len(collection) if isinstance(collection, list) else None
        total_candidate = object_data.get("total_count") if object_data else None
        total_count = (
            total_candidate if isinstance(total_candidate, int) and not isinstance(total_candidate, bool) else None
        )
        truncated = collection_size == 100 or (
            collection_size is not None and total_count is not None and total_count > collection_size
        )
        return (
            OptionalRawSource(
                True,
                result.data,
                availability="TRUNCATED" if truncated else "AVAILABLE",
                limitation=f"{label} pagination was capped at 100 records." if truncated else None,
                truncated=truncated,
            ),
            result.rate_limit_remaining,
        )
    except Exception as error:
        classified = classify_github_error(error)
        return _unavailable(f"{label} unavailable: {classified.kind}.", _error_availability(classified.kind)), None


def fetch_github_item(source: Source, dependencies: FetchDependencies | None = None) -> NormalizedGitHubFacts:
    deps = dependencies or FetchDependencies()
    rest = deps.rest or ReadOnlyRestClient()
    if isinstance(deps.graphql, _DefaultGraphql):
        graphql: GitHubGraphqlReader | None = ReadOnlyGraphqlClient() if os.environ.get("GITHUB_TOKEN") else None
    else:
        graphql = deps.graphql
    now = deps.now or _now
    delay = deps.delay or _wait
    limitations: list[str] = []
    rate_limit_remaining: int | None = None

    try:
        repository_result = rest.get_repository(source.owner, source.repo)
        item_result = (
            rest.get_pull(source.owner, source.repo, source.number)
            if source.kind == "PULL_REQUEST"
            else rest.get_issue(source.owner, source.repo, source.number)
        )
        rate_limit_remaining = (
            item_result.rate_limit_remaining
            if item_result.rate_limit_remaining is not None
            else repository_result.rate_limit_remaining
        )
    except Exception as error:
        raise classify_github_error(error) from error

    if source.kind == "PULL_REQUEST":
        for retry in range(2):
            candidate = item_result.data if isinstance(item_result.data, dict) else {}
            if candidate.get("mergeable", object()) is not None:
                break
            delay(100 * (retry + 1))
            try:
                item_result = rest.get_pull(source.owner, source.repo, source.number)
                if item_result.rate_limit_remaining is not None:
                    rate_limit_remaining = item_result.rate_limit_remaining
            except Exception as error:
                limitations.append(f"Mergeability retry failed: {classify_github_error(error).kind}.")
                break
        candidate = item_result.data if isinstance(item_result.data, dict) else {}
        if candidate.get("mergeable", object()) is None:
            limitations.append("GitHub mergeability remained UNKNOWN after bounded retries.")

    compare = _not_applicable()
    check_runs = _not_applicable()
    commit_statuses = _not_applicable()
    reviews = _not_applicable()
    commits = _not_applicable()
    if source.kind == "PULL_REQUEST":
        pull = item_result.data if isinstance(item_result.data, dict) else {}
        raw_base = pull.get("base")
        raw_head = pull.get("head")
        base: dict[str, Any] = raw_base if isinstance(raw_base, dict) else {}
        head: dict[str, Any] = raw_head if isinstance(raw_head, dict) else {}
        base_sha = base.get("sha") if isinstance(base.get("sha"), str) else None
        head_sha = head.get("sha") if isinstance(head.get("sha"), str) else None
        if base_sha and head_sha and head.get("repo", object()) is not None:
            compare, remaining = _optional(
                lambda: rest.compare(source.owner, source.repo, f"{base_sha}...{head_sha}"), "Compare data"
            )
            if remaining is not None:
                rate_limit_remaining = remaining
        else:
            compare = _unavailable("Compare data unavailable because the head repository or branch is unavailable.")
        if head_sha:
            check_runs, remaining = _optional(
                lambda: rest.get_check_runs(source.owner, source.repo, head_sha), "Check runs"
            )
            if remaining is not None:
                rate_limit_remaining = remaining
            commit_statuses, remaining = _optional(
                lambda: rest.get_commit_statuses(source.owner, source.repo, head_sha), "Commit statuses"
            )
            if remaining is not None:
                rate_limit_remaining = remaining
        reviews, remaining = _optional(lambda: rest.get_reviews(source.owner, source.repo, source.number), "Reviews")
        if remaining is not None:
            rate_limit_remaining = remaining
        commits, remaining = _optional(
            lambda: rest.get_pull_commits(source.owner, source.repo, source.number), "Pull request commits"
        )
        if remaining is not None:
            rate_limit_remaining = remaining

    comments, remaining = _optional(lambda: rest.get_comments(source.owner, source.repo, source.number), "Comments")
    if remaining is not None:
        rate_limit_remaining = remaining
    if graphql is None:
        graphql_source = _unavailable("GraphQL unavailable because GITHUB_TOKEN is not set.")
    else:
        try:
            graphql_source = OptionalRawSource(
                True,
                graphql.query_item(source.owner, source.repo, source.number, source.kind),
                availability="AVAILABLE",
            )
        except Exception as error:
            classified = classify_github_error(error)
            graphql_source = _unavailable(
                f"GraphQL data unavailable: {classified.kind}.", _error_availability(classified.kind)
            )
    raw = RawGitHubData(
        source=source,
        fetched_at=now(),
        repository=repository_result.data,
        item=item_result.data,
        compare=compare,
        check_runs=check_runs,
        commit_statuses=commit_statuses,
        reviews=reviews,
        comments=comments,
        commits=commits,
        graphql=graphql_source,
        rate_limit_remaining=rate_limit_remaining,
        limitations=limitations,
    )
    return normalize_github_data(raw)
