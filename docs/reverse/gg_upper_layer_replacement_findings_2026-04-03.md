# GG Upper-Layer Replacement Findings (2026-04-03)

## Scope

Target: `D:\gg-jy-assistant\resources\app.asar`

Goal: clarify whether GG has a general upper-layer replacement path for nested `materials.drafts` / combination clips, and extract behavior rules we should preserve in our own implementation.

## Evidence Captured

- Extracted `build/electron/` from `app.asar` into:
  - `E:\JianYingApi\VideoFactory\build\reverse_capture\gg_asar_extract_full`
- Inspected replacement-related modules:
  - `build/electron/methods/replacement/preReplaceMaterial.js`
  - `build/electron/methods/replacement/checkMaterialToReplace.js`
  - `build/electron/methods/replacement/replaceMaterial.js`
  - `build/electron/methods/replacement/refillMaterial.js`
  - `build/electron/methods/replacement/partitionRefillMaterial.js`
  - `build/electron/utils/replaceUtils.js`
- Dynamically invoked `handlePreReplaceMaterial(...)` against decrypted payloads from:
  - `E:\jycaogao\JianYingPro Drafts\4月3日 (2)\draft_content.json`
  - `E:\jycaogao\JianYingPro Drafts\4月3日 (3)\draft_content.json`

## Confirmed Findings

### 1. GG's standard replacement/refill pipeline skips combination materials

`replaceUtils.isTargetedMaterial(e, t, r, n)` returns `false` when the current segment is a combination segment whose `extra_material_refs` points into `materials.drafts`:

```js
return ... && !isCombinationVeg(r, n)
```

`isCombinationVeg(r, n)` checks:

```js
n.materials.drafts.find(function(e){ return e.id === currentSegment.extra_material_refs[x] })
```

The same skip rule appears in:

- `replaceMaterial.js`
- `refillMaterial.js`
- `partitionRefillMaterial.js`

### 2. GG's own pre-replace check rejects `4月3日 (2)` and `4月3日 (3)` as "no material"

Dynamic call result for both decrypted payloads:

```json
{
  "status": "error",
  "data": "在非锁定的视频轨道上没有任何素材。"
}
```

This matches the static skip rule above: top-level unlocked video tracks contain combination segments, and nested media inside `materials.drafts[*].draft` is intentionally ignored by the standard replacement path.

### 3. GG standard path uses minimal direct field replacement for non-combination media

In `handleReplaceMaterialsVideo(...)` and refill variants, GG mainly mutates:

- `materials.videos[*].path`
- `materials.videos[*].material_name`
- `materials.videos[*].width`
- `materials.videos[*].height`
- `materials.videos[*].duration`
- segment `speed` and `source_timerange` when replacement video duration differs

It then writes the cloned payload through `p._____(infoPath, JSONbig.stringify(payload))`.

No evidence was found in this standard path that GG rewrites official nested `templateDraft` placeholder filenames or `materials.drafts[*].draft` recursively.

## Implications For Our Implementation

1. Our nested official-combination replacement is already beyond GG's standard replacement/refill pipeline.
   - So the goal is not to "copy GG one-to-one" for nested combination materials, because that exact path appears not to perform this replacement.

2. For nested official drafts, we should keep a strict "preserve source semantics" policy:
   - preserve original schema shape (`draft_cover_path` only if source has it)
   - preserve official placeholder filenames such as `##_material_placeholder_...##_water_mark.png`
   - if donor image extension differs from the placeholder extension, transcode content into the original target extension instead of renaming the target path

3. Do not use static "missing_refs" alone as an openability verdict for official nested drafts.
   - Source official drafts themselves may contain relative mirror references that do not exist in the cloned draft folder but are still valid via `templateDraft` semantics.

## Open Questions

- Is there another GG feature path (outside standard replace/refill) that intentionally edits nested combination materials?
- If not, our product's nested official replacement path must be treated as our own extension and covered by our own regression suite.

