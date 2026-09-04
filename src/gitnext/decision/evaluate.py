"""Deterministic evaluation entry point."""

from __future__ import annotations

from typing import Any

from gitnext.decision.issue_rules import evaluate_issue_rules
from gitnext.decision.pr_rules import evaluate_pr_rules
from gitnext.decision.validate_evidence import validate_decision_evidence, validate_facts_evidence
from gitnext.domain.decision import DECISION_SCHEMA_VERSION, Decision
from gitnext.domain.facts import NormalizedGitHubFacts


def _javascript_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def evaluate(input_facts: NormalizedGitHubFacts | dict[str, Any]) -> Decision:
    facts = NormalizedGitHubFacts.model_validate(input_facts)
    validate_facts_evidence(facts)
    candidates = evaluate_pr_rules(facts) if facts.source.kind == "PULL_REQUEST" else evaluate_issue_rules(facts)
    selected = next((candidate for candidate in candidates if candidate.matched), None)
    if selected is None:
        raise RuntimeError("Decision rule set has no fallback")
    decision = Decision.model_validate(
        {
            "schemaVersion": DECISION_SCHEMA_VERSION,
            "verdict": selected.verdict,
            "ruleId": selected.rule_id,
            "reasonCode": selected.reason_code,
            "evidenceIds": selected.evidence_ids,
            "nextActionCode": selected.next_action_code,
            "responsibleParty": selected.responsible_party,
            "confidence": selected.confidence,
            "limitations": sorted(set(selected.limitations), key=_javascript_sort_key),
            "trace": [
                {
                    "ruleId": candidate.rule_id,
                    "matched": candidate.matched,
                    "reasonCode": candidate.reason_code if candidate.matched else None,
                }
                for candidate in candidates
            ],
        }
    )
    validate_decision_evidence(facts, decision)
    return decision
