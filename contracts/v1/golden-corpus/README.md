# Frozen Golden corpus

This directory contains 23 human-approved facts documents with their expected decisions, plus a raw normalization input and its complete expected normalized facts.

The corpus is frozen at contract version `1.0.0`. `manifest.json` records the SHA-256 and byte size of every other file in this directory. Tests verify these values but never write, regenerate, or accept updated expected data.

The expected decisions and normalized facts were verified against the historical TypeScript reference at commit `01a79c2174797eb45faf82cff84c9b632d8cedc1`. The standalone Python implementation was validated before extraction at `317438ecffc034d4c381cd755c3bfb6a62a6ee82`. See `docs/provenance.md` for the repository-level provenance record.
