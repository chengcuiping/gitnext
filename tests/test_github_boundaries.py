from __future__ import annotations

import copy
from typing import Any

import httpx
import pytest
from conftest import RAW_FIXTURE, load_json

from gitnext.analyze import analyze_url
from gitnext.github.fetch_item import FetchDependencies, fetch_github_item
from gitnext.github.graphql_client import ReadOnlyGraphqlClient, assert_read_only_graphql
from gitnext.github.parse_url import parse_github_url
from gitnext.github.rest_client import ReadOnlyRestClient, RestResult, assert_read_only_rest_method


@pytest.mark.parametrize(
    ("url", "kind", "number"),
    [
        ("https://github.com/openai/codex/pull/123", "PULL_REQUEST", 123),
        ("https://github.com/openai/codex/issues/42", "ISSUE", 42),
        ("https://github.com/openai/codex/pull/7/", "PULL_REQUEST", 7),
        ("https://github.com/openai/codex/issues/8?tab=activity#top", "ISSUE", 8),
    ],
)
def test_parse_url_accepts_only_supported_shapes(url: str, kind: str, number: int) -> None:
    parsed = parse_github_url(url)
    assert parsed.kind == kind
    assert parsed.number == number
    assert "?" not in parsed.canonical_url and "#" not in parsed.canonical_url


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b/pull/1",
        "https://gitlab.com/a/b/pull/1",
        "https://github.com.evil.test/a/b/pull/1",
        "https://github.com/a/b/pull/0",
        "https://github.com/a/b/pull/nope",
        "https://github.com/a/pull/1",
        "https://github.com/a/b/pull/1/files",
        "https://user:pass@github.com/a/b/issues/1",
        "https://github.com:444/a/b/issues/1",
        "https://github.com/a/b/issues/9007199254740992",
        "not a url",
    ],
)
def test_parse_url_rejects_unsafe_input(url: str) -> None:
    with pytest.raises(ValueError):
        parse_github_url(url)


class FixtureRest:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.calls: list[str] = []
        self.pull_calls = 0

    def _result(self, name: str, data: Any) -> RestResult:
        self.calls.append(name)
        return RestResult(data, 80)

    def get_repository(self, owner: str, repo: str) -> RestResult:
        return self._result("repository", self.raw["repository"])

    def get_issue(self, owner: str, repo: str, number: int) -> RestResult:
        return self._result("issue", self.raw["item"])

    def get_pull(self, owner: str, repo: str, number: int) -> RestResult:
        self.pull_calls += 1
        return self._result("pull", self.raw["item"])

    def compare(self, owner: str, repo: str, basehead: str) -> RestResult:
        return self._result("compare", self.raw["compare"]["data"])

    def get_check_runs(self, owner: str, repo: str, ref: str) -> RestResult:
        return self._result("checks", self.raw["checkRuns"]["data"])

    def get_commit_statuses(self, owner: str, repo: str, ref: str) -> RestResult:
        return self._result("statuses", self.raw["commitStatuses"]["data"])

    def get_reviews(self, owner: str, repo: str, number: int) -> RestResult:
        return self._result("reviews", self.raw["reviews"]["data"])

    def get_comments(self, owner: str, repo: str, number: int) -> RestResult:
        return self._result("comments", self.raw["comments"]["data"])

    def get_pull_commits(self, owner: str, repo: str, number: int) -> RestResult:
        return self._result("commits", self.raw["commits"]["data"])


def test_invalid_url_is_rejected_before_any_network_request() -> None:
    rest = FixtureRest(load_json(RAW_FIXTURE))
    with pytest.raises(ValueError):
        analyze_url("https://evil.example/a/b/pull/1", FetchDependencies(rest=rest, graphql=None))
    assert rest.calls == []


def test_read_only_protocol_guards() -> None:
    assert_read_only_rest_method("GET")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(ValueError, match="rejected"):
            assert_read_only_rest_method(method)
    assert_read_only_graphql("query Read { viewer { login } }")
    with pytest.raises(ValueError, match="mutation rejected"):
        assert_read_only_graphql("mutation Write { addComment(input: {}) { clientMutationId } }")


def test_no_token_keeps_graphql_unavailable_and_rest_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    raw = load_json(RAW_FIXTURE)
    rest = FixtureRest(raw)
    facts = fetch_github_item(
        parse_github_url("https://github.com/example/project/pull/7"),
        FetchDependencies(rest=rest, now=lambda: raw["fetchedAt"]),
    )
    assert facts.availability.graphql == "UNAVAILABLE"
    assert facts.reviews.unresolved_thread_count is None
    assert "GraphQL unavailable because GITHUB_TOKEN is not set." in facts.limitations
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        ReadOnlyGraphqlClient()


def test_mergeability_retry_is_bounded_to_two_additional_reads() -> None:
    raw = load_json(RAW_FIXTURE)
    raw["item"] = copy.deepcopy(raw["item"])
    raw["item"]["mergeable"] = None
    rest = FixtureRest(raw)
    delays: list[int] = []
    facts = fetch_github_item(
        parse_github_url("https://github.com/example/project/pull/7"),
        FetchDependencies(
            rest=rest,
            graphql=None,
            now=lambda: raw["fetchedAt"],
            delay=delays.append,
        ),
    )
    assert rest.pull_calls == 3
    assert delays == [100, 200]
    assert facts.item.mergeable is None
    assert "GitHub mergeability remained UNKNOWN after bounded retries." in facts.limitations


def test_rest_collection_requests_are_get_only_and_capped_at_100() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"check_runs": []}, headers={"x-ratelimit-remaining": "0"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url="https://api.github.com", transport=transport)
    reader = ReadOnlyRestClient(client)
    result = reader.get_check_runs("owner", "repo", "sha")
    assert result.rate_limit_remaining == 0
    assert observed[0].method == "GET"
    assert observed[0].url.params["per_page"] == "100"
    client.close()
