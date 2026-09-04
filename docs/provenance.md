# Provenance

This standalone Python implementation was extracted from the former combined repository without importing its Git history.

- The Python implementation originated in commit `b8998cb7149c07361d63fda6358c422cb3cf320c`.
- Distribution hardening originated in commit `317438ecffc034d4c381cd755c3bfb6a62a6ee82`.
- The historical TypeScript reference implementation is preserved at <https://github.com/chengcuiping/gitnext-typescript-archive>.
- The frozen reference contract version is `1.0.0`; its release commit is `01a79c2174797eb45faf82cff84c9b632d8cedc1`.
- Before extraction, Python passed all 23 Golden cases and complete cross-language decision and normalization conformance checks against that frozen reference.

The Golden decisions and normalization output are now immutable language-neutral JSON fixtures with SHA-256 verification. Building, installing, running, and testing this repository has no dependency on the archived repository or its toolchain.
