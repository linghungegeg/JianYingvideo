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


def enqueue_batch_generation(
    template_id: int,
    materials_root: str,
    texts_input,
    batch_count: int,
    replace_materials: bool = True,
    replace_texts: bool = True,
    replace_type: str = "both",
    replace_mode: str = "order",
    audio_enabled: bool = False,
    effects_config: Optional[Dict[str, Any]] = None,
    duo_config: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> ServiceResult:
    template = TemplateModel.query.get(template_id)
    if not template:
        return ServiceResult(False, "template not found", code="not_found")

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
        audio_enabled,
        effects_config or {},
        duo_config or {},
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
