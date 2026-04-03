# Draft Strategy Split (2026-04-03)

## Current Rule

The bottom codec is unified, but upper-layer replacement now intentionally splits into two strategy branches based on payload structure.

### 1. Official nested template drafts

Detection:

- payload contains nested `materials.drafts[*].draft`
- nested `path` resolves to external `templateDraft` cache semantics

Strategy:

- `official_minimal_rewrite`
- preserve official placeholder filenames such as `##_material_placeholder_...##_water_mark.png`
- preserve official schema shape and external cache semantics
- do not mutate official nested thumbnail cache files in the stable path

### 2. Self-built placeholder drafts

Detection:

- payload contains `##_draftpath_placeholder_...##`

Strategy:

- `selfbuilt_grouped_placeholder_rewrite`
- treat the placeholder image set as a grouped rewrite, not sparse single-image patching
- update encrypted payload and plain timeline mirror together
- keep `material_name` / `name` blank when the source material kept them blank

## Verified Samples

- Official:
  - `E:\jycaogao\JianYingPro Drafts\4月3日`
  - `E:\jycaogao\JianYingPro Drafts\4月3日 (1)`
  - `E:\jycaogao\JianYingPro Drafts\4月3日 (2)`
  - `E:\jycaogao\JianYingPro Drafts\4月3日 (3)`
- Self-built:
  - `E:\jycaogao\JianYingPro Drafts\0314-01`

## Why This Split Exists

GG's standard replacement pipeline does not cover nested combination materials under `materials.drafts`. Our official nested replacement path is therefore our own extension, while self-built placeholder drafts follow a different upper-layer path shape and cannot be forced into the same sparse replacement rules.
