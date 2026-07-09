# Fix duplicate content gap scoring

## Status
Open

## Priority
Medium

## Problem

`tests/test_content_gap.py::test_exact_duplicate_detected`

- Expected: `gap_score < 25`
- Current: `gap_score = 35`

## Notes

This issue predates the Feed Intelligence work.
Do not modify it as part of the current feature set.

## Acceptance Criteria

- Exact duplicates receive a significantly lower content gap score.
- Existing behavior for partial duplicates remains unchanged.
- All content gap tests pass.
- No regression to Feed Intelligence modules.
