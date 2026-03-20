# Legacy Template Endpoint Switch

The old template-library endpoints are still available for compatibility, but they can now be disabled with one config switch.

## Env Var

```env
LEGACY_TEMPLATE_ENDPOINTS_ENABLED=0
```

## Behavior

- `1`: keep `/api/template/<id>/configure` and `/api/template/<id>/tracks` available as deprecated compatibility endpoints.
- `0`: return `410` with a deprecated response payload and direct callers to local `draft_path` flows.

## Recommended Rollout

1. Keep it at `0` by default for local desktop and EXE builds.
2. Only set it to `1` if you explicitly need temporary compatibility with old callers.
3. Verify no remaining callers depend on `template_id` endpoints.
4. Remove the endpoints completely after one stable release cycle.
