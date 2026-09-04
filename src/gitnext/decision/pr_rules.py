"""Pull-request rule table, ported without semantic changes from TypeScript v1."""

from __future__ import annotations

from dataclasses import dataclass, field

from gitnext.decision.rule_ids import PR_RULES
from gitnext.domain.decision import Confidence, ResponsibleParty, Verdict
from gitnext.domain.facts import NormalizedGitHubFacts, SourceAvailability

MAX_DECISION_EVIDENCE_IDS = 10
MAX_FAILED_CHECK_SAMPLES_WITH_SUMMARY = MAX_DECISION_EVIDENCE_IDS - 1


@dataclass(frozen=True)
class RuleCandidate:
    rule_id: str
    matched: bool
    verdict: Verdict
    reason_code: str
    evidence_ids: list[str]
    next_action_code: str
    responsible_party: ResponsibleParty
    confidence: Confidence
    limitations: list[str] = field(default_factory=list)


def _source_readable(value: SourceAvailability) -> bool:
    return value in {"AVAILABLE", "TRUNCATED"}


def _ids_present(facts: NormalizedGitHubFacts, ids: list[str]) -> bool:
    available = {item.id for item in facts.evidence}
    return bool(ids) and all(evidence_id in available for evidence_id in ids)


def evaluate_pr_rules(facts: NormalizedGitHubFacts) -> list[RuleCandidate]:
    evidence = {item.id for item in facts.evidence}

    def field_id(evidence_id: str) -> list[str]:
        return [evidence_id] if evidence_id in evidence else []

    item = facts.item
    repo = facts.repository
    checks = facts.checks.items or []
    reviews = facts.reviews.latest_review_per_reviewer or []

    repo_ids = [
        *(field_id("repository.archived") if repo.archived else []),
        *(field_id("repository.disabled") if repo.disabled else []),
    ]
    conflict_ids = [
        *(field_id("branches.mergeable") if item.mergeable is False else []),
        *(field_id("branches.mergeStateStatus") if (item.merge_state_status or "") in {"DIRTY", "CONFLICTING"} else []),
    ]
    failed_ids = [check.evidence_id for check in checks if check.status == "FAILURE"]
    check_summary_id = (
        facts.checks.summary_evidence_id
        if facts.checks.summary_evidence_id and facts.checks.summary_evidence_id in evidence
        else None
    )
    failed_decision_ids = (
        [check_summary_id, *failed_ids[:MAX_FAILED_CHECK_SAMPLES_WITH_SUMMARY]]
        if len(failed_ids) > MAX_DECISION_EVIDENCE_IDS and check_summary_id
        else failed_ids[:MAX_DECISION_EVIDENCE_IDS]
    )
    rest_changes_ids = [
        review.evidence_id for review in reviews if review.state == "CHANGES_REQUESTED" and not review.dismissed
    ]
    graphql_changes_ids = (
        [facts.reviews.review_decision_evidence_id]
        if facts.reviews.review_decision == "CHANGES_REQUESTED" and facts.reviews.review_decision_evidence_id
        else []
    )
    graphql_review_available = _source_readable(facts.availability.graphql)
    changes_ids = graphql_changes_ids if graphql_review_available else rest_changes_ids
    changes_decision_ids = changes_ids[:MAX_DECISION_EVIDENCE_IDS]
    pending_ids = [check.evidence_id for check in checks if check.status == "PENDING"]
    pending_decision_ids = [check_summary_id] if check_summary_id else pending_ids[:MAX_DECISION_EVIDENCE_IDS]
    thread_ids = (
        [facts.reviews.unresolved_threads_evidence_id]
        if facts.reviews.unresolved_thread_count is not None
        and facts.reviews.unresolved_thread_count > 0
        and facts.reviews.unresolved_threads_evidence_id
        else []
    )
    rest_approval_ids = (
        [review.evidence_id for review in reviews if review.state == "APPROVED" and not review.dismissed]
        if facts.reviews.rest_review_history_complete
        else []
    )
    graphql_review_ids = (
        [facts.reviews.review_decision_evidence_id]
        if facts.reviews.review_decision == "APPROVED" and facts.reviews.review_decision_evidence_id
        else []
    )
    review_required_ids = (
        [facts.reviews.review_decision_evidence_id]
        if graphql_review_available
        and facts.reviews.review_decision == "REVIEW_REQUIRED"
        and facts.reviews.review_decision_evidence_id
        else []
    )
    positive_ids = [
        *(
            [check_summary_id]
            if facts.checks.summary and facts.checks.summary.success_count > 0 and check_summary_id
            else []
        ),
        *(graphql_review_ids if graphql_review_available else rest_approval_ids[:1]),
        *(field_id("branches.mergeable") if item.mergeable is True else []),
    ]
    review_state_reliable = (
        facts.reviews.review_decision != "UNKNOWN"
        if graphql_review_available
        else _source_readable(facts.availability.pull_request_reviews) and facts.reviews.rest_review_history_complete
    )
    open_evidence_ids = [
        *field_id("item.state"),
        *field_id("item.draft"),
        *([check_summary_id] if check_summary_id else []),
        *(
            [facts.reviews.review_decision_evidence_id]
            if graphql_review_available and facts.reviews.review_decision_evidence_id
            else rest_approval_ids[:1]
        ),
        *(
            [facts.reviews.unresolved_threads_evidence_id]
            if facts.reviews.unresolved_threads_complete and facts.reviews.unresolved_threads_evidence_id
            else []
        ),
        *field_id("branches.mergeable"),
        *field_id("branches.mergeStateStatus"),
        *positive_ids,
    ]
    open_ready = (
        item.state == "OPEN"
        and item.draft is False
        and facts.reviews.review_decision != "REVIEW_REQUIRED"
        and review_state_reliable
        and not failed_ids
        and not changes_ids
        and not conflict_ids
        and not thread_ids
        and not pending_ids
        and bool(positive_ids)
    )
    open_limitations = [
        *facts.limitations,
        *([] if facts.checks.requiredness_known else ["Required check configuration is unknown."]),
        *([] if facts.reviews.unresolved_threads_available else ["Unresolved review threads are unavailable."]),
    ]

    return [
        RuleCandidate(
            PR_RULES["MERGED"],
            item.merged is True and _ids_present(facts, field_id("item.merged")),
            "DONE_OR_STOP",
            "PR_ALREADY_MERGED",
            field_id("item.merged"),
            "STOP_PR_WORK",
            "NONE",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["CLOSED"],
            item.state == "CLOSED"
            and item.merged is False
            and _ids_present(facts, [*field_id("item.state"), *field_id("item.merged")]),
            "DONE_OR_STOP",
            "PR_CLOSED_UNMERGED",
            [*field_id("item.state"), *field_id("item.merged")],
            "STOP_OR_REASSESS",
            "NONE",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["REPOSITORY_INACTIVE"],
            (repo.archived or repo.disabled) and _ids_present(facts, repo_ids),
            "DONE_OR_STOP",
            "REPOSITORY_ARCHIVED" if repo.archived else "REPOSITORY_DISABLED",
            repo_ids,
            "STOP_REPOSITORY_INACTIVE",
            "NONE",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["DRAFT"],
            item.draft is True and _ids_present(facts, field_id("item.draft")),
            "AUTHOR_ACTION_REQUIRED",
            "PR_IS_DRAFT",
            field_id("item.draft"),
            "MARK_READY_FOR_REVIEW",
            "AUTHOR",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["CONFLICT"],
            bool(conflict_ids) and _ids_present(facts, conflict_ids),
            "SYNC_OR_FIX_BRANCH",
            "EXPLICIT_BRANCH_CONFLICT",
            conflict_ids,
            "RESOLVE_BRANCH_CONFLICT",
            "AUTHOR",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["CHECK_FAILURE"],
            bool(failed_ids) and _ids_present(facts, failed_decision_ids),
            "AUTHOR_ACTION_REQUIRED",
            "LATEST_CHECK_FAILED",
            failed_decision_ids,
            "FIX_FAILED_CHECKS",
            "AUTHOR",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["CHANGES_REQUESTED"],
            bool(changes_ids) and _ids_present(facts, changes_decision_ids),
            "AUTHOR_ACTION_REQUIRED",
            "LATEST_REVIEW_CHANGES_REQUESTED",
            changes_decision_ids,
            "ADDRESS_REVIEW_CHANGES",
            "AUTHOR",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["UNRESOLVED_THREAD"],
            facts.reviews.unresolved_threads_available and bool(thread_ids) and _ids_present(facts, thread_ids),
            "AUTHOR_ACTION_REQUIRED",
            "UNRESOLVED_REVIEW_THREADS",
            thread_ids,
            "RESOLVE_REVIEW_THREADS",
            "AUTHOR",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["CHECK_PENDING"],
            bool(pending_ids) and _ids_present(facts, pending_decision_ids),
            "WAIT",
            "WAITING_FOR_CI",
            pending_decision_ids,
            "WAIT_FOR_CI",
            "CI",
            "MEDIUM",
        ),
        RuleCandidate(
            PR_RULES["REVIEW_REQUIRED"],
            bool(review_required_ids) and _ids_present(facts, review_required_ids),
            "WAIT",
            "REVIEW_REQUIRED",
            review_required_ids,
            "WAIT_FOR_REVIEW",
            "REVIEWER",
            "HIGH",
        ),
        RuleCandidate(
            PR_RULES["NO_AUTHOR_BLOCKER"],
            open_ready and _ids_present(facts, open_evidence_ids),
            "WAIT",
            "NO_KNOWN_AUTHOR_BLOCKER",
            list(dict.fromkeys(open_evidence_ids))[:MAX_DECISION_EVIDENCE_IDS],
            "WAIT_FOR_MAINTAINER",
            "MAINTAINER",
            "LOW" if open_limitations else "MEDIUM",
            open_limitations,
        ),
        RuleCandidate(
            PR_RULES["FALLBACK"],
            True,
            "INSUFFICIENT_EVIDENCE",
            "INSUFFICIENT_PR_EVIDENCE",
            [],
            "GATHER_MORE_EVIDENCE",
            "UNKNOWN",
            "LOW",
            facts.limitations,
        ),
    ]
