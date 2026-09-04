from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest
from conftest import CONTRACT_CASES, REPOSITORY_ROOT, load_json
from pydantic import ValidationError

from gitnext.decision.evaluate import evaluate
from gitnext.decision.rule_ids import ISSUE_RULES, PR_RULES
from gitnext.decision.validate_evidence import EvidenceValidationError
from gitnext.domain.decision import DECISION_SCHEMA_VERSION, Decision, decision_to_dict
from gitnext.domain.facts import FACTS_SCHEMA_VERSION, NormalizedGitHubFacts


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def golden_cases() -> list[dict[str, Any]]:
    return [load_json(path) for path in sorted(CONTRACT_CASES.glob("*.json"))]


def test_all_23_human_approved_golden_cases_are_exact_and_deterministic() -> None:
    cases = golden_cases()
    assert len(cases) == 23
    for case in cases:
        assert case["approval"]["humanApproved"] is True
        facts = NormalizedGitHubFacts.model_validate(case["facts"])
        expected = Decision.model_validate(case["decision"])
        assert facts.schema_version == FACTS_SCHEMA_VERSION == "1.0.0"
        assert expected.schema_version == DECISION_SCHEMA_VERSION == "1.0.0"
        actual = decision_to_dict(evaluate(facts))
        assert actual == case["decision"], case["caseId"]
        expected_bytes = canonical_bytes(actual)
        for iteration in range(100):
            replay = decision_to_dict(evaluate(copy.deepcopy(case["facts"])))
            assert canonical_bytes(replay) == expected_bytes, (case["caseId"], iteration)


def test_golden_corpus_manifest_hashes_are_complete_and_frozen() -> None:
    corpus_root = CONTRACT_CASES.parent
    manifest = load_json(corpus_root / "manifest.json")
    assert manifest["contractVersion"] == "1.0.0"
    assert manifest["status"] == "FROZEN"
    assert manifest["caseCount"] == 23
    assert manifest["determinismReplaysPerCase"] == 100
    expected_paths = {item["path"] for item in manifest["files"]}
    actual_paths = {
        path.relative_to(corpus_root).as_posix()
        for path in corpus_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert expected_paths == actual_paths
    for item in manifest["files"]:
        payload = (corpus_root / item["path"]).read_bytes()
        assert len(payload) == item["bytes"], item["path"]
        assert hashlib.sha256(payload).hexdigest() == item["sha256"], item["path"]


def test_all_expected_decision_evidence_is_bounded_and_present() -> None:
    for case in golden_cases():
        evidence_ids = {item["id"] for item in case["facts"]["evidence"]}
        decision_ids = case["decision"]["evidenceIds"]
        assert len(decision_ids) <= 10, case["caseId"]
        assert set(decision_ids) <= evidence_ids, case["caseId"]


def test_rule_id_order_is_frozen() -> None:
    rules = load_json(REPOSITORY_ROOT / "contracts" / "v1" / "rules.json")
    assert [item["ruleId"] for item in rules["pullRequestRules"]] == list(PR_RULES.values())
    assert [item["ruleId"] for item in rules["issueRules"]] == list(ISSUE_RULES.values())


def test_dangling_fact_evidence_fails_closed() -> None:
    case = golden_cases()[0]
    facts = copy.deepcopy(case["facts"])
    referenced_id = facts["checks"]["items"][0]["evidenceId"]
    facts["evidence"] = [item for item in facts["evidence"] if item["id"] != referenced_id]
    with pytest.raises(EvidenceValidationError, match="Dangling fact evidence IDs"):
        evaluate(facts)


def test_decision_evidence_limit_is_ten() -> None:
    value = copy.deepcopy(golden_cases()[0]["decision"])
    value["evidenceIds"] = [f"evidence-{index}" for index in range(11)]
    with pytest.raises(ValidationError):
        Decision.model_validate(value)


def test_many_failed_checks_use_summary_plus_nine_deterministic_samples() -> None:
    facts = copy.deepcopy(golden_cases()[0]["facts"])
    facts["evidence"] = [
        item for item in facts["evidence"] if not item["id"].startswith("check.") and item["id"] != "checks.summary"
    ]
    checks = []
    for index in range(105):
        evidence_id = f"check.synthetic-{index:03d}.status"
        checks.append(
            {
                "key": f"synthetic-{index:03d}",
                "name": f"synthetic-{index:03d}",
                "provider": "CHECK_RUN",
                "status": "FAILURE",
                "requiredness": "UNKNOWN",
                "detailsUrl": facts["source"]["canonicalUrl"],
                "updatedAt": facts["fetchedAt"],
                "evidenceId": evidence_id,
            }
        )
        facts["evidence"].append(
            {
                "id": evidence_id,
                "category": "check",
                "claim": evidence_id,
                "value": "FAILURE",
                "sourceUrl": facts["source"]["canonicalUrl"],
                "apiSource": "fixture.check",
                "observedAt": facts["fetchedAt"],
            }
        )
    summary = {
        "failureCount": 105,
        "pendingCount": 0,
        "successCount": 0,
        "skippedCount": 0,
        "neutralCount": 0,
        "cancelledCount": 0,
        "unknownCount": 0,
        "observedCheckCount": 105,
        "collectionComplete": True,
        "truncated": False,
    }
    facts["checks"] = {
        "items": checks,
        "requirednessKnown": False,
        "summary": summary,
        "summaryEvidenceId": "checks.summary",
    }
    facts["evidence"].append(
        {
            "id": "checks.summary",
            "category": "check_summary",
            "claim": "Synthetic check summary",
            "value": summary,
            "sourceUrl": facts["source"]["canonicalUrl"],
            "apiSource": "fixture.checkSummary",
            "observedAt": facts["fetchedAt"],
        }
    )
    decision = evaluate(facts)
    assert decision.rule_id == "PR_006_CHECK_FAILURE"
    assert len(decision.evidence_ids) == 10
    assert decision.evidence_ids[0] == "checks.summary"
    assert decision.evidence_ids[1:] == [f"check.synthetic-{index:03d}.status" for index in range(9)]


def test_limitations_are_deduplicated_and_javascript_sorted() -> None:
    case = next(item for item in golden_cases() if item["decision"]["ruleId"] == "ISSUE_007_INSUFFICIENT_EVIDENCE")
    facts = copy.deepcopy(case["facts"])
    facts["limitations"] = ["z limitation", "a limitation", "z limitation"]
    decision = decision_to_dict(evaluate(facts))
    assert decision["limitations"] == ["a limitation", "z limitation"]
