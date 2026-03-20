import os
from typing import Any, Dict, Optional

from redis import Redis
from rq import Queue
from flask import current_app

from app.extensions import db
from app.models.task import Task
from app.models.template_model import TemplateModel
from app.tasks import generate_video_task
from app.services.jianying.result import ServiceResult


def _get_redis_url() -> str:
    try:
        return current_app.config.get("REDIS_URL")
    except Exception:
        return os.getenv("REDIS_URL", "")


def _enqueue_generation_job(
    template_id: Optional[int],
    template_path: str,
    materials_root: str,
    texts_input,
    batch_count: int,
    replace_materials: bool = True,
    replace_texts: bool = True,
    replace_type: str = "both",
    replace_mode: str = "order",
    replace_strategy: str = "group",
    audio_enabled: bool = False,
    export_enabled: bool = False,
    export_path: Optional[str] = None,
    export_format: Optional[str] = None,
    export_resolution: Optional[str] = None,
    export_fps: Optional[int] = None,
    effects_config: Optional[Dict[str, Any]] = None,
    duo_config: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> ServiceResult:
    redis_url = _get_redis_url()
    if not redis_url:
        return ServiceResult(False, "REDIS_URL not set", code="config_error")

    redis_conn = Redis.from_url(redis_url)
    task_queue = Queue(connection=redis_conn)

    job = task_queue.enqueue(
        generate_video_task,
        template_id,
        materials_root,
        texts_input,
        batch_count,
        replace_materials,
        replace_texts,
        replace_type,
        replace_mode,
        replace_strategy,
        audio_enabled,
        export_enabled,
        export_path,
        export_format,
        export_resolution,
        export_fps,
        effects_config or {},
        duo_config or {},
        user_id,
        template_path,
    )

    task = Task(
        id=job.id,
        user_id=user_id,
        template_id=template_id,
        status="pending",
    )
    db.session.add(task)
    db.session.commit()

    return ServiceResult(True, "enqueued", data={"job_id": job.id})


def enqueue_batch_generation_by_template_id(
    template_id: int,
    materials_root: str,
    texts_input,
    batch_count: int,
    replace_materials: bool = True,
    replace_texts: bool = True,
    replace_type: str = "both",
    replace_mode: str = "order",
    replace_strategy: str = "group",
    audio_enabled: bool = False,
    export_enabled: bool = False,
    export_path: Optional[str] = None,
    export_format: Optional[str] = None,
    export_resolution: Optional[str] = None,
    export_fps: Optional[int] = None,
    effects_config: Optional[Dict[str, Any]] = None,
    duo_config: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> ServiceResult:
    # Legacy compatibility entry. New code should pass draft_path instead.
    template = TemplateModel.query.get(template_id)
    if not template:
        return ServiceResult(False, "legacy template not found", code="not_found")
    result = _enqueue_generation_job(
        template_id=template_id,
        template_path=template.template_path,
        materials_root=materials_root,
        texts_input=texts_input,
        batch_count=batch_count,
        replace_materials=replace_materials,
        replace_texts=replace_texts,
        replace_type=replace_type,
        replace_mode=replace_mode,
        replace_strategy=replace_strategy,
        audio_enabled=audio_enabled,
        export_enabled=export_enabled,
        export_path=export_path,
        export_format=export_format,
        export_resolution=export_resolution,
        export_fps=export_fps,
        effects_config=effects_config,
        duo_config=duo_config,
        user_id=user_id,
    )
    if result.ok:
        payload = result.data or {}
        payload["deprecated"] = True
        payload["legacy_mode"] = "template_id"
        result.data = payload
        result.message = "template_id is legacy compatibility only; prefer draft_path"
    return result


def enqueue_batch_generation(
    template_id: int,
    materials_root: str,
    texts_input,
    batch_count: int,
    replace_materials: bool = True,
    replace_texts: bool = True,
    replace_type: str = "both",
    replace_mode: str = "order",
    replace_strategy: str = "group",
    audio_enabled: bool = False,
    export_enabled: bool = False,
    export_path: Optional[str] = None,
    export_format: Optional[str] = None,
    export_resolution: Optional[str] = None,
    export_fps: Optional[int] = None,
    effects_config: Optional[Dict[str, Any]] = None,
    duo_config: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> ServiceResult:
    # Backward-compatible alias. Prefer enqueue_batch_generation_by_template_id().
    return enqueue_batch_generation_by_template_id(
        template_id=template_id,
        materials_root=materials_root,
        texts_input=texts_input,
        batch_count=batch_count,
        replace_materials=replace_materials,
        replace_texts=replace_texts,
        replace_type=replace_type,
        replace_mode=replace_mode,
        replace_strategy=replace_strategy,
        audio_enabled=audio_enabled,
        export_enabled=export_enabled,
        export_path=export_path,
        export_format=export_format,
        export_resolution=export_resolution,
        export_fps=export_fps,
        effects_config=effects_config,
        duo_config=duo_config,
        user_id=user_id,
    )


def enqueue_batch_generation_by_path(
    draft_path: str,
    materials_root: str,
    texts_input,
    batch_count: int,
    replace_materials: bool = True,
    replace_texts: bool = True,
    replace_type: str = "both",
    replace_mode: str = "order",
    replace_strategy: str = "group",
    audio_enabled: bool = False,
    export_enabled: bool = False,
    export_path: Optional[str] = None,
    export_format: Optional[str] = None,
    export_resolution: Optional[str] = None,
    export_fps: Optional[int] = None,
    effects_config: Optional[Dict[str, Any]] = None,
    duo_config: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> ServiceResult:
    if not draft_path:
        return ServiceResult(False, "draft_path is required", code="not_found")
    result = _enqueue_generation_job(
        template_id=None,
        template_path=draft_path,
        materials_root=materials_root,
        texts_input=texts_input,
        batch_count=batch_count,
        replace_materials=replace_materials,
        replace_texts=replace_texts,
        replace_type=replace_type,
        replace_mode=replace_mode,
        replace_strategy=replace_strategy,
        audio_enabled=audio_enabled,
        export_enabled=export_enabled,
        export_path=export_path,
        export_format=export_format,
        export_resolution=export_resolution,
        export_fps=export_fps,
        effects_config=effects_config,
        duo_config=duo_config,
        user_id=user_id,
    )
    if result.ok:
        payload = result.data or {}
        payload["legacy_mode"] = None
        result.data = payload
    return result


def enqueue_local_batch_generation(
    draft_path: str,
    materials_root: str,
    texts_input,
    batch_count: int,
    replace_materials: bool = True,
    replace_texts: bool = True,
    replace_type: str = "both",
    replace_mode: str = "order",
    replace_strategy: str = "group",
    audio_enabled: bool = False,
    export_enabled: bool = False,
    export_path: Optional[str] = None,
    export_format: Optional[str] = None,
    export_resolution: Optional[str] = None,
    export_fps: Optional[int] = None,
    effects_config: Optional[Dict[str, Any]] = None,
    duo_config: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> ServiceResult:
    return enqueue_batch_generation_by_path(
        draft_path=draft_path,
        materials_root=materials_root,
        texts_input=texts_input,
        batch_count=batch_count,
        replace_materials=replace_materials,
        replace_texts=replace_texts,
        replace_type=replace_type,
        replace_mode=replace_mode,
        replace_strategy=replace_strategy,
        audio_enabled=audio_enabled,
        export_enabled=export_enabled,
        export_path=export_path,
        export_format=export_format,
        export_resolution=export_resolution,
        export_fps=export_fps,
        effects_config=effects_config,
        duo_config=duo_config,
        user_id=user_id,
    )
