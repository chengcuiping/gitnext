"""Issue rule table, ported without semantic changes from TypeScript v1."""

import re
from urllib.parse import quote

from gitnext.decision.pr_rules import MAX_DECISION_EVIDENCE_IDS, RuleCandidate
from gitnext.decision.rule_ids import ISSUE_RULES
from gitnext.domain.facts import NormalizedGitHubFacts

DUPLICATE_LABELS = {"duplicate", "status: duplicate", "type: duplicate"}
NEEDS_INFO_LABELS = {
    "needs-info",
    "needs info",
    "status: needs-info",
    "status: needs info",
    "needs-repro",
    "needs repro",
    "needs-reproduction",
    "needs reproduction",
}


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _encode_uri_component(value: str) -> str:
    return quote(value, safe="~()*!.'-_")


def evaluate_issue_rules(facts: NormalizedGitHubFacts) -> list[RuleCandidate]:
    present = {item.id for item in facts.evidence}

    def existing(ids: list[str]) -> list[str]:
        return [evidence_id for evidence_id in ids if evidence_id in present]

    duplicate_ids = [
        f"label.{_encode_uri_component(_normalized(label))}"
        for label in facts.links.explicit_duplicate_labels
        if _normalized(label) in DUPLICATE_LABELS
    ][:MAX_DECISION_EVIDENCE_IDS]
    merged_pr_ids = [pull.evidence_id for pull in (facts.links.closing_pull_requests or []) if pull.merged is True][
        :MAX_DECISION_EVIDENCE_IDS
    ]
    needs_info_ids = [
        f"label.{_encode_uri_component(_normalized(label))}"
        for label in facts.item.labels
        if _normalized(label) in NEEDS_INFO_LABELS
    ][:MAX_DECISION_EVIDENCE_IDS]
    open_linked_pr_ids = [
        pull.evidence_id for pull in (facts.links.linked_pull_requests or []) if pull.state == "OPEN"
    ][:MAX_DECISION_EVIDENCE_IDS]
    repo_ids = [
        *(["repository.archived"] if facts.repository.archived else []),
        *(["repository.disabled"] if facts.repository.disabled else []),
    ]
    return [
        RuleCandidate(
            ISSUE_RULES["CLOSED"],
            facts.item.state == "CLOSED" and "item.state" in present,
            "DONE_OR_STOP",
            "ISSUE_CLOSED",
            ["item.state"],
            "STOP_ISSUE_WORK",
            "NONE",
            "HIGH",
        ),
        RuleCandidate(
            ISSUE_RULES["REPOSITORY_INACTIVE"],
            (facts.repository.archived or facts.repository.disabled) and bool(existing(repo_ids)),
            "DONE_OR_STOP",
            "REPOSITORY_ARCHIVED" if facts.repository.archived else "REPOSITORY_DISABLED",
            existing(repo_ids),
            "STOP_REPOSITORY_INACTIVE",
            "NONE",
            "HIGH",
        ),
        RuleCandidate(
            ISSUE_RULES["DUPLICATE"],
            bool(existing(duplicate_ids)),
            "DONE_OR_STOP",
            "EXPLICIT_DUPLICATE_LABEL",
            existing(duplicate_ids),
            "FOLLOW_CANONICAL_ITEM",
            "NONE",
            "HIGH",
        ),
        RuleCandidate(
            ISSUE_RULES["LINKED_MERGED_PR"],
            bool(existing(merged_pr_ids)),
            "DONE_OR_STOP",
            "EXPLICIT_LINKED_PR_MERGED",
            existing(merged_pr_ids),
            "VERIFY_RELEASE_OR_STOP",
            "NONE",
            "HIGH",
        ),
        RuleCandidate(
            ISSUE_RULES["NEEDS_INFO"],
            bool(existing(needs_info_ids)),
            "AUTHOR_ACTION_REQUIRED",
            "ISSUE_NEEDS_INFORMATION",
            existing(needs_info_ids),
            "PROVIDE_REQUESTED_INFORMATION",
            "AUTHOR",
            "HIGH",
        ),
        RuleCandidate(
            ISSUE_RULES["OPEN_LINKED_PR"],
            bool(existing(open_linked_pr_ids)),
            "WAIT",
            "OPEN_LINKED_PR_EXISTS",
            existing(open_linked_pr_ids),
            "WAIT_FOR_LINKED_PR",
            "ASSIGNEE_OR_CONTRIBUTOR",
            "MEDIUM",
            facts.limitations,
        ),
        RuleCandidate(
            ISSUE_RULES["FALLBACK"],
            True,
            "INSUFFICIENT_EVIDENCE",
            "INSUFFICIENT_ISSUE_EVIDENCE",
            [],
            "GATHER_MORE_EVIDENCE",
            "UNKNOWN",
            "LOW",
            facts.limitations,
        ),
    ]
