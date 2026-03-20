# Optional Feature Switches

These switches are intended for lean desktop and EXE builds.

## Defaults

```env
DUO_FEATURES_ENABLED=0
OPENCLAW_FEATURES_ENABLED=0
MANGA_FEATURES_ENABLED=0
```

## Covered Route Groups

- `DUO_FEATURES_ENABLED`
  Blocks `/api/duo/*`

- `OPENCLAW_FEATURES_ENABLED`
  Blocks `/api/openclaw/*`

- `MANGA_FEATURES_ENABLED`
  Blocks `/api/manga/*` and `/api/ai/manga/*`

## Recommendation

- Keep these switches at `0` for desktop builds focused on local Jianying draft processing.
- Only set a switch to `1` if that feature group is part of the product scope for the packaged build.
