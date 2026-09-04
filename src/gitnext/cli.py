"""GitNext Python command-line interface."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gitnext.analyze import analyze_url
from gitnext.decision.evaluate import evaluate
from gitnext.domain.decision import decision_to_dict
from gitnext.domain.facts import NormalizedGitHubFacts, facts_to_dict
from gitnext.github.errors import GitHubAccessError, GitHubInputError

USAGE = "Usage: gitnext <github-url> | gitnext --fixture <facts.json>"


def _write_result(facts: NormalizedGitHubFacts) -> None:
    result = {"facts": facts_to_dict(facts), "decision": decision_to_dict(evaluate(facts))}
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def main(args: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if args is None else args)
    if values in (["--help"], ["-h"]):
        print(USAGE)
        return 0
    if not (len(values) == 1 and not values[0].startswith("-")) and not (len(values) == 2 and values[0] == "--fixture"):
        print(USAGE, file=sys.stderr)
        return 2
    try:
        if values[0] == "--fixture":
            raw: Any = json.loads(Path(values[1]).read_text(encoding="utf-8"))
            candidate = raw.get("facts") if isinstance(raw, dict) and "facts" in raw else raw
            _write_result(NormalizedGitHubFacts.model_validate(candidate))
            return 0
        result = analyze_url(values[0])
        payload = {"facts": facts_to_dict(result.facts), "decision": decision_to_dict(result.decision)}
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0
    except GitHubInputError as error:
        print(
            json.dumps({"error": {"kind": error.kind, "code": error.code, "message": str(error)}}),
            file=sys.stderr,
        )
        return 2
    except GitHubAccessError as error:
        print(
            json.dumps({"error": {"kind": error.kind, "message": str(error), "status": error.status}}),
            file=sys.stderr,
        )
        return 4 if error.kind in {"INVALID_RESPONSE", "INTERNAL"} else 3
    except Exception as error:
        print(
            json.dumps({"error": {"kind": "INTERNAL", "message": str(error) or "Unknown internal error"}}),
            file=sys.stderr,
        )
        return 4


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
