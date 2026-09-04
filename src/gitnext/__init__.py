"""GitNext Python v1 contract implementation."""

from gitnext.analyze import AnalysisResult, analyze_url
from gitnext.decision.evaluate import evaluate
from gitnext.domain.decision import DECISION_SCHEMA_VERSION, Decision
from gitnext.domain.facts import FACTS_SCHEMA_VERSION, NormalizedGitHubFacts
from gitnext.github.fetch_item import fetch_github_item
from gitnext.github.normalize import normalize_github_data
from gitnext.github.parse_url import parse_github_url

__all__ = [
    "DECISION_SCHEMA_VERSION",
    "FACTS_SCHEMA_VERSION",
    "AnalysisResult",
    "Decision",
    "NormalizedGitHubFacts",
    "analyze_url",
    "evaluate",
    "fetch_github_item",
    "normalize_github_data",
    "parse_github_url",
]

__version__ = "0.1.0"
