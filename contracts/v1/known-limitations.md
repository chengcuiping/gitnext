# GitNext v1 known limitations and live coverage

GitNext does not determine that a pull request can be merged or is ready to merge. It emits conservative next-step advice from visible, bounded GitHub facts.

## Known limitations

- Required-check configuration is not collected, so check requiredness remains `UNKNOWN`; a failed check asks the author to inspect it without claiming that it is required or code-caused.
- Collections have an explicit 100-record bound. Truncation remains visible in availability and limitations.
- GraphQL availability and repository permissions can leave partial facts.
- Comment text, assignees, item age, and natural-language relationships are not used to infer semantic relationships or abandonment.
- A deleted head repository prevents branch comparison; missing comparison data is never converted to a conflict or zero divergence.

## Stable-live coverage gaps accepted for v1

- `PR_004_DRAFT`
- `PR_007_CHANGES_REQUESTED`
- `PR_011_NO_KNOWN_AUTHOR_BLOCKER`
- `PR_012_INSUFFICIENT_EVIDENCE`

Each gap has offline fixture/regression coverage and does not block v1.0.0.

## LIVE_COVERAGE_WAIVED_RARE

- `PR_003_REPOSITORY_INACTIVE`: reachable when an open PR remains in an archived or disabled repository.
- `ISSUE_004_LINKED_MERGED_PR`: reachable for an open or reopened Issue with an explicit merged closing PR; ordinary merge-driven closure is selected earlier by `ISSUE_001_CLOSED`.
