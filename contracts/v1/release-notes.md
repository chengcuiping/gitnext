# GitNext deterministic contract v1.0.0

This release freezes facts, decision, rule-priority, evidence, and availability semantics at v1.0.0 after human approval of 23 stable public Golden Cases.

GitNext does not determine that a pull request can be merged or is ready to merge. It provides conservative next-step advice based only on visible GitHub facts.

Stable-live coverage remains absent for `PR_004_DRAFT`, `PR_007_CHANGES_REQUESTED`, `PR_011_NO_KNOWN_AUTHOR_BLOCKER`, and `PR_012_INSUFFICIENT_EVIDENCE`; offline fixtures and regressions cover them. Rare live coverage waivers remain for `PR_003_REPOSITORY_INACTIVE` and `ISSUE_004_LINKED_MERGED_PR`. These accepted gaps do not block v1.0.0.
