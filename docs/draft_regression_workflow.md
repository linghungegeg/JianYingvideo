# Draft Regression Workflow

## Goal

Run a fixed regression set that now covers both:

- official nested template drafts
- self-built placeholder drafts

The replacement service now exposes the detected draft kind and replacement strategy in diagnostics.

## Verified Template Set

Use:

- `E:\JianYingApi\VideoFactory\packaging\draft_regression_templates_2026-04-03.json`

This set currently includes:

- `4月3日`
- `4月3日 (1)`
- `4月3日 (2)`
- `4月3日 (3)`
- `0314-01`

## Command

```powershell
python scripts/official_draft_regression.py `
  --use-verified-template-set `
  --keep-output `
  --report-json "E:\JianYingApi\VideoFactory\build\official_draft_regression\verified_2026-04-03.json"
```

## What To Check In The Report

- `failed_count`
- `strategy_counts`
- each probe's:
  - `draft_kind`
  - `replacement_strategy`
  - `scan.total_missing_refs`

Expected strategy split:

- official drafts:
  - `official_nested_template_draft`
  - `official_minimal_rewrite`
- self-built drafts:
  - `selfbuilt_placeholder_draft`
  - `selfbuilt_grouped_placeholder_rewrite`

## Manual Acceptance

Static scan is not enough.

Final acceptance still requires opening the generated probe draft in Jianying and confirming:

- the draft opens
- media is not missing
- replaced visuals/text/audio actually changed in the editor
