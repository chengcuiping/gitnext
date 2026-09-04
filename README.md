# GitNext

GitNext is a read-only Python library and CLI that turns visible GitHub pull-request or issue facts into conservative, deterministic next-step advice. It implements the frozen GitNext facts and decision contract version `1.0.0`.

GitNext does not claim that a pull request is safe or ready to merge. It does not write to GitHub, execute repository code, or infer relationships from comment prose.

## Requirements and installation

GitNext requires Python 3.10 or newer. Its only runtime dependencies are Pydantic 2 and httpx.

```bash
python -m pip install gitnext
```

The project is not published by this repository's CI. For development from a clone:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

On Windows, use `.venv\\Scripts\\python` in place of `.venv/bin/python`.

## CLI

Analyze a public GitHub pull request or issue:

```bash
gitnext https://github.com/OWNER/REPO/pull/123
gitnext https://github.com/OWNER/REPO/issues/123
```

Evaluate a local normalized facts document without network access:

```bash
gitnext --fixture contracts/v1/golden-corpus/cases/01-vllm-54166.json
```

Successful commands write one JSON object containing `facts` and `decision` to stdout. Diagnostics are JSON on stderr. Exit codes are 0 for a completed analysis, 2 for invalid input, 3 for GitHub access, rate-limit, or network errors, and 4 for invalid responses or internal contract failures.

`GITHUB_TOKEN` is optional and is the only credential source. Public REST reads work without it; GraphQL is explicitly unavailable when it is absent. GitNext never reads `.env`, GitHub CLI configuration, or authentication files, and never prints or persists the token.

## SDK

```python
import json
from pathlib import Path

from gitnext import evaluate
from gitnext.domain.decision import decision_to_dict

case = json.loads(Path("contracts/v1/golden-corpus/cases/01-vllm-54166.json").read_text())
decision = decision_to_dict(evaluate(case["facts"]))
```

For live, read-only analysis, use `gitnext.analyze_url`. URL validation occurs before any network request.

## Frozen conformance corpus

The repository contains 23 human-approved normalized fact sets and their expected decisions. The test suite validates full semantic equality, canonical JSON bytes, 100 deterministic replays per case (2,300 total), normalization parity against frozen expected facts, evidence integrity, the ten-ID evidence bound, and preservation of unknown, null, false, and zero semantics.

The Golden corpus has a SHA-256 manifest and no update or acceptance path in the tests. Its historical cross-language validation is documented in [docs/provenance.md](docs/provenance.md); running and testing this repository requires only Python and does not depend on the archived implementation.

## Development gates

```bash
python -m pytest
python -m mypy src
python -m ruff check .
python -m ruff format --check .
python -m build
python -m twine check dist/*
python tools/audit_repository.py
python tools/audit_distribution.py dist
python tools/secret_scan.py
```

CI covers Python 3.10 through 3.14 on Ubuntu, plus installation and CLI smoke tests on Windows and macOS.

## Safety and limitations

- REST exposes GET only; GraphQL accepts query operations only and rejects mutations.
- Collections are capped at 100 records, with truncation represented explicitly.
- Required-check configuration is not fetched, so requiredness stays `UNKNOWN`.
- Reviews and source availability can be permission-dependent; unavailable evidence lowers confidence or causes a conservative fallback.
- Only GitHub-provided explicit links and exact supported labels establish relationships.
- The package performs no GitHub writes and contains no publishing automation.

See [contracts/v1/known-limitations.md](contracts/v1/known-limitations.md) for the frozen contract limitations.

## License

Copyright 2026 chengcuiping.

GitNext is licensed under the [Apache License 2.0](LICENSE). Apache-2.0 grants no trademark rights in GitNext, the project name, or its branding.
