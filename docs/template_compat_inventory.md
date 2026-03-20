# Template Compatibility Inventory

This document tracks the remaining `TemplateModel` and `template_id` usage after the local `draft_path` workflow became the primary path.

## Remaining Runtime References

- [`app/views/api.py`](/E:/JianYingApi/VideoFactory/app/views/api.py)
  `/api/generate`
  Legacy-compatible entry. Accepts `template_id`, but the preferred path is `draft_path`.

- [`app/views/api.py`](/E:/JianYingApi/VideoFactory/app/views/api.py)
  `/api/template/<id>/configure`
  Legacy endpoint. Already marked deprecated.

- [`app/views/api.py`](/E:/JianYingApi/VideoFactory/app/views/api.py)
  `/api/template/<id>/tracks`
  Legacy endpoint. Already marked deprecated.

- [`app/views/mcp_api.py`](/E:/JianYingApi/VideoFactory/app/views/mcp_api.py)
  `/api/mcp/batch/enqueue`
  Still accepts `template_id` as compatibility input. `draft_path` is preferred and checked first.

- [`app/services/jianying/batch_service.py`](/E:/JianYingApi/VideoFactory/app/services/jianying/batch_service.py)
  `enqueue_batch_generation_by_template_id()`
  Explicit legacy wrapper that resolves `TemplateModel` and delegates into the normal queue path.

- [`app/tasks.py`](/E:/JianYingApi/VideoFactory/app/tasks.py)
  `generate_video_task(...)`
  Final fallback only. If `template_path` is missing, it will still try to resolve `template_id`.

## Non-Blocking References

- [`app/models/task.py`](/E:/JianYingApi/VideoFactory/app/models/task.py)
  `template_id` column remains for backward compatibility and historical task records.

- [`app/utils/helpers.py`](/E:/JianYingApi/VideoFactory/app/utils/helpers.py)
  Generation logs still record `template_id` when present.

## Recommended Removal Order

1. Stop sending `template_id` from all external callers.
2. Remove `/api/template/<id>/configure` and `/api/template/<id>/tracks`.
3. Remove `template_id` support from `/api/generate` and `/api/mcp/batch/enqueue`.
4. Delete `enqueue_batch_generation_by_template_id()`.
5. Remove the `template_id` fallback from `generate_video_task(...)`.
6. Decide whether the `tasks.template_id` column should be kept for history or migrated away.
