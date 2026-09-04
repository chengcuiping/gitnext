"""Small GET-only GitHub REST client with bounded collection requests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx


def assert_read_only_rest_method(method: str) -> None:
    if method.upper() != "GET":
        raise ValueError(f"GitHub REST write method rejected: {method.upper()}")


@dataclass(frozen=True)
class RestResult:
    data: Any
    rate_limit_remaining: int | None


class GitHubRestReader(Protocol):
    def get_repository(self, owner: str, repo: str) -> RestResult: ...

    def get_issue(self, owner: str, repo: str, number: int) -> RestResult: ...

    def get_pull(self, owner: str, repo: str, number: int) -> RestResult: ...

    def compare(self, owner: str, repo: str, basehead: str) -> RestResult: ...

    def get_check_runs(self, owner: str, repo: str, ref: str) -> RestResult: ...

    def get_commit_statuses(self, owner: str, repo: str, ref: str) -> RestResult: ...

    def get_reviews(self, owner: str, repo: str, number: int) -> RestResult: ...

    def get_comments(self, owner: str, repo: str, number: int) -> RestResult: ...

    def get_pull_commits(self, owner: str, repo: str, number: int) -> RestResult: ...


def _part(value: str) -> str:
    return quote(value, safe="")


class ReadOnlyRestClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        token = os.environ.get("GITHUB_TOKEN")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "gitnext-python/0.1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = client or httpx.Client(base_url="https://api.github.com", headers=headers, timeout=20.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(self, path: str, parameters: dict[str, str | int] | None = None) -> RestResult:
        assert_read_only_rest_method("GET")
        response = self._client.get(path, params=parameters)
        response.raise_for_status()
        raw_remaining = response.headers.get("x-ratelimit-remaining")
        try:
            remaining = int(raw_remaining) if raw_remaining is not None else None
        except ValueError:
            remaining = None
        if remaining is not None and remaining < 0:
            remaining = None
        return RestResult(response.json(), remaining)

    def get_repository(self, owner: str, repo: str) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}")

    def get_issue(self, owner: str, repo: str, number: int) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/issues/{number}")

    def get_pull(self, owner: str, repo: str, number: int) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/pulls/{number}")

    def compare(self, owner: str, repo: str, basehead: str) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/compare/{_part(basehead)}")

    def get_check_runs(self, owner: str, repo: str, ref: str) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/commits/{_part(ref)}/check-runs", {"per_page": 100})

    def get_commit_statuses(self, owner: str, repo: str, ref: str) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/commits/{_part(ref)}/statuses", {"per_page": 100})

    def get_reviews(self, owner: str, repo: str, number: int) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/pulls/{number}/reviews", {"per_page": 100})

    def get_comments(self, owner: str, repo: str, number: int) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/issues/{number}/comments", {"per_page": 100})

    def get_pull_commits(self, owner: str, repo: str, number: int) -> RestResult:
        return self._get(f"/repos/{_part(owner)}/{_part(repo)}/pulls/{number}/commits", {"per_page": 100})
