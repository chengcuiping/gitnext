"""Pydantic representation of the frozen GitNext v1 decision contract."""

from typing import Literal

from pydantic import Field

from gitnext.domain.evidence import ContractModel

DECISION_SCHEMA_VERSION = "1.0.0"

Verdict = Literal["AUTHOR_ACTION_REQUIRED", "SYNC_OR_FIX_BRANCH", "WAIT", "DONE_OR_STOP", "INSUFFICIENT_EVIDENCE"]
ResponsibleParty = Literal["AUTHOR", "MAINTAINER", "REVIEWER", "CI", "ASSIGNEE_OR_CONTRIBUTOR", "NONE", "UNKNOWN"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class TraceEntry(ContractModel):
    rule_id: str
    matched: bool
    reason_code: str | None


class Decision(ContractModel):
    schema_version: Literal["1.0.0"]
    verdict: Verdict
    rule_id: str
    reason_code: str
    evidence_ids: list[str] = Field(max_length=10)
    next_action_code: str
    responsible_party: ResponsibleParty
    confidence: Confidence
    limitations: list[str]
    trace: list[TraceEntry]


def decision_to_dict(decision: Decision) -> dict[str, object]:
    return decision.model_dump(by_alias=True, mode="json")
