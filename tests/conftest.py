from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_CASES = REPOSITORY_ROOT / "contracts" / "v1" / "golden-corpus" / "cases"
NORMALIZATION_CORPUS = REPOSITORY_ROOT / "contracts" / "v1" / "golden-corpus" / "normalization"
RAW_FIXTURE = NORMALIZATION_CORPUS / "input.json"
EXPECTED_FACTS = NORMALIZATION_CORPUS / "expected-facts.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
