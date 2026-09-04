# Contributing

Thank you for contributing to GitNext.

## Development setup

Use Python 3.10 or newer and a project-local virtual environment:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Before opening a pull request, run the gates listed in the README: pytest, mypy, Ruff lint and format checks, package builds, distribution audits, and the secret scan.

## Contract changes

The files under `contracts/v1` are frozen. Do not regenerate, overwrite, or automatically accept Golden expected results. A proposal to change behavior must use a new contract version and explain compatibility, evidence semantics, rule priority, and migration impact.

GitNext must remain deterministic and read-only. Do not add GitHub mutations, repository code execution, time-dependent decisions, randomness, or model calls. Never commit credentials or local environment files.
