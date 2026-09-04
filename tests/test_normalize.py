from __future__ import annotations

import copy
from typing import Any

import pytest
from conftest import EXPECTED_FACTS, RAW_FIXTURE, load_json

from gitnext.decision.evaluate import evaluate
from gitnext.domain.facts import facts_to_dict
from gitnext.github.errors import GitHubAccessError
from gitnext.github.normalize import normalize_github_data


def raw_fixture() -> dict[str, Any]:
    return load_json(RAW_FIXTURE)


def test_raw_fixture_normalizes_latest_checks_reviews_links_and_activity() -> None:
    facts = facts_to_dict(normalize_github_data(raw_fixture()))
    assert len(facts["checks"]["items"]) == 2
    checks = {item["name"]: item for item in facts["checks"]["items"]}
    assert checks["ci"]["status"] == "SUCCESS"
    assert checks["lint"]["status"] == "PENDING"
    assert facts["reviews"]["approvedReviewers"] == ["reviewer"]
    assert facts["reviews"]["changesRequestedReviewers"] == []
    assert len(facts["reviews"]["dismissedReviews"]) == 1
    assert facts["branches"] | {"mergeable": True} == facts["branches"]
    assert facts["reviews"]["unresolvedThreadCount"] == 1
    assert facts["links"]["linkedIssues"][0]["number"] == 3
    assert facts["activity"]["lastMaintainerActivityAt"] == "2026-01-02T06:00:00.000Z"


def test_raw_fixture_matches_frozen_normalization_facts_completely() -> None:
    actual = facts_to_dict(normalize_github_data(load_json(RAW_FIXTURE)))
    assert actual == load_json(EXPECTED_FACTS)


def test_graphql_controls_a_conflicting_rest_review() -> None:
    raw = raw_fixture()
    raw["reviews"]["data"] = [
        {
            "id": 90,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-01-02T03:00:00Z",
            "html_url": "https://github.com/example/project/pull/7#pullrequestreview-90",
            "user": {"login": "reviewer"},
            "author_association": "MEMBER",
        }
    ]
    facts = normalize_github_data(raw)
    assert facts.reviews.review_decision == "APPROVED"
    assert any("GraphQL reviewDecision conflicts" in value for value in facts.limitations)
    assert evaluate(facts).rule_id != "PR_007_CHANGES_REQUESTED"


def test_incomplete_thread_connection_preserves_known_blocker() -> None:
    raw = raw_fixture()
    threads = raw["graphql"]["data"]["repository"]["pullRequest"]["reviewThreads"]
    threads["pageInfo"]["hasNextPage"] = True
    facts = normalize_github_data(raw)
    assert facts.reviews.unresolved_thread_count == 1
    assert facts.reviews.unresolved_threads_available is True
    assert facts.reviews.unresolved_threads_complete is False
    assert facts.availability.review_threads == "TRUNCATED"
    assert evaluate(facts).rule_id == "PR_008_UNRESOLVED_THREAD"


def test_truncated_rest_history_cannot_supply_a_positive_unblocked_conclusion() -> None:
    raw = raw_fixture()
    raw["reviews"]["truncated"] = True
    raw["graphql"] = {"available": False, "data": None, "limitation": "GraphQL unavailable."}
    raw["checkRuns"]["data"]["check_runs"] = [raw["checkRuns"]["data"]["check_runs"][1]]
    raw["commitStatuses"]["data"][0]["state"] = "success"
    raw["commitStatuses"]["data"] = [raw["commitStatuses"]["data"][0]]
    facts = normalize_github_data(raw)
    assert facts.reviews.rest_review_history_complete is False
    assert evaluate(facts).rule_id == "PR_012_INSUFFICIENT_EVIDENCE"


def test_unknown_null_false_and_zero_remain_distinct() -> None:
    raw = raw_fixture()
    raw["item"]["comments"] = 0
    raw["item"]["mergeable"] = None
    raw["graphql"]["data"]["repository"]["pullRequest"]["reviewDecision"] = "NOVEL_STATE"
    facts = normalize_github_data(raw)
    assert facts.item.comments_count == 0
    assert facts.item.draft is False
    assert facts.item.merged is False
    assert facts.item.mergeable is None
    assert facts.reviews.review_decision == "UNKNOWN"
    raw["graphql"]["data"]["repository"]["pullRequest"]["reviewDecision"] = None
    assert normalize_github_data(raw).reviews.review_decision is None


def _as_issue(raw: dict[str, Any]) -> dict[str, Any]:
    issue = copy.deepcopy(raw)
    issue["source"] = {
        "originalUrl": "https://github.com/example/project/issues/9",
        "canonicalUrl": "https://github.com/example/project/issues/9",
        "owner": "example",
        "repo": "project",
        "number": 9,
        "kind": "ISSUE",
    }
    issue["item"] = {
        "state": "open",
        "state_reason": None,
        "title": "Issue",
        "user": {"login": "reporter"},
        "author_association": "CONTRIBUTOR",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "closed_at": None,
        "labels": [],
        "assignees": [{"login": "maintainer"}],
        "locked": False,
        "comments": 0,
        "html_url": "https://github.com/example/project/issues/9",
    }
    for key in ("compare", "checkRuns", "commitStatuses", "reviews", "commits"):
        issue[key] = {"available": False, "data": None}
    issue["graphql"] = {"available": False, "data": None, "limitation": "GraphQL unavailable."}
    return issue


def test_issue_pr_sources_are_not_applicable_and_assignee_alone_does_not_imply_work() -> None:
    facts = normalize_github_data(_as_issue(raw_fixture()))
    assert facts.availability.branch_comparison == "NOT_APPLICABLE"
    assert facts.availability.check_runs == "NOT_APPLICABLE"
    assert facts.availability.commit_statuses == "NOT_APPLICABLE"
    assert facts.availability.pull_request_commits == "NOT_APPLICABLE"
    assert facts.availability.pull_request_reviews == "NOT_APPLICABLE"
    assert facts.availability.review_threads == "NOT_APPLICABLE"
    assert all("NOT_APPLICABLE" not in value for value in facts.limitations)
    decision = evaluate(facts)
    assert decision.rule_id == "ISSUE_007_INSUFFICIENT_EVIDENCE"
    assert decision.responsible_party == "UNKNOWN"


def test_issue_explicit_duplicate_and_linked_pr_semantics() -> None:
    raw = _as_issue(raw_fixture())
    raw["item"]["labels"] = [{"name": "status: duplicate"}]
    raw["graphql"] = {
        "available": True,
        "data": {
            "repository": {
                "issue": {
                    "closedByPullRequestsReferences": {
                        "nodes": [
                            {
                                "number": 10,
                                "url": "https://github.com/example/project/pull/10",
                                "state": "CLOSED",
                                "merged": True,
                                "repository": {"nameWithOwner": "example/project"},
                            }
                        ],
                        "pageInfo": {"hasNextPage": False},
                    }
                }
            }
        },
    }
    facts = normalize_github_data(raw)
    assert facts.links.explicit_duplicate_labels == ["status: duplicate"]
    assert facts.links.closing_pull_requests is not None
    assert facts.links.closing_pull_requests[0].merged is True
    assert evaluate(facts).rule_id == "ISSUE_003_EXPLICIT_DUPLICATE"


@pytest.mark.parametrize("field,value", [("state", "invalid"), ("created_at", "not-a-time")])
def test_invalid_core_state_or_timestamp_fails_closed(field: str, value: str) -> None:
    raw = raw_fixture()
    raw["item"][field] = value
    with pytest.raises(GitHubAccessError) as caught:
        normalize_github_data(raw)
    assert caught.value.kind == "INVALID_RESPONSE"


def test_empty_commit_status_url_is_preserved_as_contract_null() -> None:
    raw = raw_fixture()
    raw["commitStatuses"]["data"] = [
        {
            "id": 99,
            "context": "ofborg-eval",
            "state": "success",
            "target_url": "",
            "created_at": "2026-01-02T02:00:00Z",
            "updated_at": "2026-01-02T02:00:00Z",
        }
    ]
    facts = normalize_github_data(raw)
    status = next(item for item in facts.checks.items or [] if item.name == "ofborg-eval")
    assert status.details_url is None
