"""Fail-closed evidence integrity checks."""

from gitnext.domain.decision import Decision
from gitnext.domain.facts import NormalizedGitHubFacts


class EvidenceValidationError(ValueError):
    """Raised when facts or a decision references absent evidence."""


def validate_facts_evidence(facts: NormalizedGitHubFacts) -> None:
    ids = {item.id for item in facts.evidence}
    if len(ids) != len(facts.evidence):
        raise EvidenceValidationError("Evidence IDs must be unique")
    referenced = [
        *(item.evidence_id for item in (facts.checks.items or [])),
        *([facts.checks.summary_evidence_id] if facts.checks.summary_evidence_id else []),
        *(item.evidence_id for item in (facts.reviews.latest_review_per_reviewer or [])),
        *(item.evidence_id for item in (facts.reviews.dismissed_reviews or [])),
        *([facts.reviews.review_decision_evidence_id] if facts.reviews.review_decision_evidence_id else []),
        *([facts.reviews.unresolved_threads_evidence_id] if facts.reviews.unresolved_threads_evidence_id else []),
        *(item.evidence_id for item in (facts.links.linked_issues or [])),
        *(item.evidence_id for item in (facts.links.linked_pull_requests or [])),
        *(item.evidence_id for item in (facts.links.closing_pull_requests or [])),
        *(item.evidence_id for item in (facts.links.linked_commits or [])),
    ]
    dangling = list(dict.fromkeys(evidence_id for evidence_id in referenced if evidence_id not in ids))
    if dangling:
        raise EvidenceValidationError(f"Dangling fact evidence IDs: {', '.join(dangling)}")


def validate_decision_evidence(facts: NormalizedGitHubFacts, decision: Decision) -> None:
    ids = {item.id for item in facts.evidence}
    dangling = [evidence_id for evidence_id in decision.evidence_ids if evidence_id not in ids]
    if dangling:
        raise EvidenceValidationError(f"Dangling decision evidence IDs: {', '.join(dangling)}")
    if decision.verdict != "INSUFFICIENT_EVIDENCE" and not decision.evidence_ids:
        raise EvidenceValidationError("A decisive verdict must reference evidence")
