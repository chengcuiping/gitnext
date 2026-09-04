"""Query-only GitHub GraphQL client."""

from __future__ import annotations

import os
import re
from typing import Any, Protocol

import httpx

from gitnext.domain.facts import ItemKind
from gitnext.github.errors import GitHubAccessError


class GitHubGraphqlReader(Protocol):
    def query_item(self, owner: str, repo: str, number: int, kind: ItemKind) -> Any: ...


def assert_read_only_graphql(document: str) -> None:
    without_comments = re.sub(r"#[^\n]*", " ", document).lstrip()
    if re.search(r"\bmutation\b", without_comments, flags=re.IGNORECASE):
        raise ValueError("GitHub GraphQL mutation rejected")
    if not (without_comments.startswith("{") or re.match(r"^query\b", without_comments, flags=re.IGNORECASE)):
        raise ValueError("Only GraphQL query operations are allowed")


PR_QUERY = """query GitNextPullRequest($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewDecision
      reviewThreads(first: 100) { nodes { id isResolved } pageInfo { hasNextPage } }
      closingIssuesReferences(first: 100) {
        nodes { number url state repository { nameWithOwner } }
        pageInfo { hasNextPage }
      }
    }
  }
}"""

ISSUE_QUERY = """query GitNextIssue($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      closedByPullRequestsReferences(first: 100) {
        nodes { number url state merged repository { nameWithOwner } }
        pageInfo { hasNextPage }
      }
    }
  }
}"""


class ReadOnlyGraphqlClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise GitHubAccessError("FORBIDDEN", "GITHUB_TOKEN is required for GitHub GraphQL")
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "gitnext-python/0.1.0",
        }
        self._client = client or httpx.Client(headers=headers, timeout=20.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def query_item(self, owner: str, repo: str, number: int, kind: ItemKind) -> Any:
        document = PR_QUERY if kind == "PULL_REQUEST" else ISSUE_QUERY
        assert_read_only_graphql(document)
        response = self._client.post(
            "https://api.github.com/graphql",
            json={"query": document, "variables": {"owner": owner, "repo": repo, "number": number}},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise GitHubAccessError("INVALID_RESPONSE", "GitHub GraphQL returned an invalid response")
        if payload.get("errors"):
            raise GitHubAccessError("INVALID_RESPONSE", "GitHub GraphQL returned errors")
        return payload["data"]
