"""High-level GitNext analysis API."""

from __future__ import annotations

from dataclasses import dataclass

from gitnext.decision.evaluate import evaluate
from gitnext.domain.decision import Decision
from gitnext.domain.facts import NormalizedGitHubFacts
from gitnext.github.fetch_item import FetchDependencies, fetch_github_item
from gitnext.github.parse_url import parse_github_url


@dataclass(frozen=True)
class AnalysisResult:
    facts: NormalizedGitHubFacts
    decision: Decision


def analyze_url(url: str, dependencies: FetchDependencies | None = None) -> AnalysisResult:
    parsed = parse_github_url(url)
    facts = fetch_github_item(parsed, dependencies)
    return AnalysisResult(facts=facts, decision=evaluate(facts))
