import datetime
import json
import logging
import os
import importlib
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
from app.utils.runtime_paths import app_resource_path, runtime_path

from app.utils.jianying_mcp.services.track_service import create_track_service
from app.utils.jianying_mcp.services.video_service import (
    add_video_segment_service,
    add_video_animation_service,
    add_video_transition_service,
    add_video_filter_service,
    add_video_mask_service,
    add_video_keyframe_service,
    add_video_background_filling_service,
    add_video_effect_service,
)
from app.utils.jianying_mcp.services.audio_service import (
    add_audio_segment_service,
    add_audio_effect_service,
    add_audio_fade_service,
    add_audio_keyframe_service,
)
from app.utils.jianying_mcp.services.text_service import (
    add_text_segment_service,
    add_text_animation_service,
)
from app.utils.jianying_mcp.utils.effect_manager import JianYingResourceManager
from app.utils.jianying_mcp.utils.media_parser import MediaParser

from app.utils.jianying_mcp.jianying.export import ExportDraft
from app.utils.jianying_mcp.jianying.text import TextSegment
from app.utils.jianying_mcp.utils.index_manager import index_manager
from app.utils.jianying_mcp.utils.response import ToolResponse

from app.services.jianying.config import JianYingConfig
from app.services.jianying.errors import ValidationError, NotFoundError
from app.services.jianying.result import ServiceResult, from_tool_response
from app.services.jianying.validators import require_path, require_timerange, require_non_empty


load_dotenv()


class JianYingService:
    """
    JianYing MCP 统一服务层：封装草稿/轨道/视频/音频/文本/工具能力。

    示例用法:
        svc = JianYingService()

        # 草稿
        draft = svc.create_draft("demo", width=1080, height=1920, fps=30)
        draft_id = draft.data["draft_id"]

        # 轨道
        video_track = svc.create_track(draft_id, "video")
        text_track = svc.create_track(draft_id, "text")

        # 视频片段
        seg = svc.add_video_segment(
            draft_id,
            material="D:/materials/clip.mp4",
            target_timerange="0s-3s",
            track_name=video_track.data["track_name"] if video_track.data else None
        )

        # 文本片段
        txt = svc.add_text_segment(
            draft_id,
            text="Hello",
            timerange="0s-3s",
            track_name=text_track.data.get("track_name") if text_track.data else None
        )

        # 文字动画
        svc.add_text_animation(
            draft_id,
            text_segment_id=txt.data["text_segment_id"],
            animation_type="TextIntro",
            animation_name="弹跳"
        )

        # 导出
        svc.export_draft(draft_id, jianying_draft_path="D:/JianyingPro Drafts")
    """

    def __init__(
        self,
        save_path: Optional[str] = None,
        output_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        runtime_save_path = save_path or os.getenv("SAVE_PATH", "")
        if not runtime_save_path:
            runtime_save_path = str(runtime_path("mcp_cache"))
        os.makedirs(runtime_save_path, exist_ok=True)
        os.environ["SAVE_PATH"] = runtime_save_path
        if output_path:
            os.environ["OUTPUT_PATH"] = output_path
        self._refresh_runtime_paths()
        self.config = JianYingConfig.from_env()
        self.logger = logger or logging.getLogger("jianying_service")

    def _refresh_runtime_paths(self) -> None:
        save_path = os.getenv("SAVE_PATH", "")
        output_path = os.getenv("OUTPUT_PATH", "")
        module_attr_map = {
            "app.utils.jianying_mcp.jianying.audio": ("SAVE_PATH",),
            "app.utils.jianying_mcp.jianying.draft": ("SAVE_PATH",),
            "app.utils.jianying_mcp.jianying.export": ("SAVE_PATH", "OUTPUT_PATH"),
            "app.utils.jianying_mcp.jianying.text": ("SAVE_PATH",),
            "app.utils.jianying_mcp.jianying.track": ("SAVE_PATH",),
            "app.utils.jianying_mcp.jianying.video": ("SAVE_PATH",),
            "app.utils.jianying_mcp.tool.draft_tool": ("SAVE_PATH", "OUTPUT_PATH"),
            "app.utils.jianying_mcp.utils.draft_maintenance": ("SAVE_PATH",),
            "app.utils.jianying_mcp.utils.index_manager": ("SAVE_PATH",),
            "app.utils.jianying_mcp.validators.material_validator": ("SAVE_PATH",),
            "app.utils.jianying_mcp.validators.overlap_validator": ("SAVE_PATH",),
        }
        for module_name, attrs in module_attr_map.items():
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            for attr in attrs:
                if attr == "SAVE_PATH":
                    setattr(module, attr, save_path)
                elif attr == "OUTPUT_PATH":
                    setattr(module, attr, output_path)
            if module_name == "app.utils.jianying_mcp.utils.index_manager":
                manager = getattr(module, "index_manager", None)
                if manager:
                    manager.index_file_path = os.path.join(save_path, "global_index.json")
                    manager._ensure_index_file()

    def _get_draft_scaffold_path(self) -> str:
        candidate = str(app_resource_path("runtime_tools", "jianying_draft_scaffold"))
        return candidate if os.path.isdir(candidate) else ""

    def _copy_missing_entry(self, source_path: str, target_path: str) -> None:
        if os.path.exists(target_path):
            return
        if os.path.isdir(source_path):
            shutil.copytree(source_path, target_path)
            return
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(source_path, target_path)

    def _load_json_dict(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _write_json_dict(self, path: str, payload: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload or {}, handle, ensure_ascii=False, indent=2)

    def _candidate_root_meta_paths(self) -> list[str]:
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return [
            os.path.normpath(
                os.path.join(
                    local_app_data,
                    "JianyingPro",
                    "User Data",
                    "Projects",
                    "com.lveditor.draft",
                    "root_meta_info.json",
                )
            )
        ]

    def _sync_exported_draft_meta(self, exported_dir: str, draft_content_path: str) -> dict:
        meta_path = os.path.join(exported_dir, "draft_meta_info.json")
        meta = self._load_json_dict(meta_path)
        if not meta:
            return {}

        draft_name = os.path.basename(exported_dir.rstrip("\\/"))
        draft_root_path = os.path.normpath(os.path.dirname(exported_dir))
        draft_file_size = 0
        draft_duration = 0
        if os.path.isfile(draft_content_path):
            try:
                draft_file_size = int(os.path.getsize(draft_content_path) or 0)
            except Exception:
                draft_file_size = 0
            draft_payload = self._load_json_dict(draft_content_path)
            try:
                draft_duration = int(draft_payload.get("duration") or 0)
            except Exception:
                draft_duration = 0

        now_us = int(time.time() * 1_000_000)
        draft_id = str(meta.get("draft_id") or "").strip() or str(uuid.uuid4()).upper()
        meta["draft_id"] = draft_id
        meta["draft_name"] = draft_name
        meta["draft_fold_path"] = exported_dir.replace("\\", "/")
        meta["draft_root_path"] = draft_root_path
        meta["draft_json_file"] = draft_content_path.replace("\\", "/")
        meta["draft_cover"] = "draft_cover.jpg"
        meta["draft_need_rename_folder"] = False
        meta["draft_is_invisible"] = False
        meta["draft_timeline_materials_size_"] = draft_file_size
        if draft_duration > 0:
            meta["tm_duration"] = draft_duration
        if not meta.get("tm_draft_create"):
            meta["tm_draft_create"] = now_us
        meta["tm_draft_modified"] = now_us
        if not str(meta.get("draft_removable_storage_device") or "").strip():
            drive, _tail = os.path.splitdrive(exported_dir)
            meta["draft_removable_storage_device"] = drive or ""
        self._write_json_dict(meta_path, meta)
        return meta

    def _build_root_meta_entry(self, meta: dict, exported_dir: str, draft_content_path: str) -> dict:
        draft_file_size = int(meta.get("draft_timeline_materials_size_") or 0)
        return {
            "cloud_draft_cover": bool(meta.get("cloud_draft_cover", False)),
            "cloud_draft_sync": bool(meta.get("cloud_draft_sync", False)),
            "draft_cloud_last_action_download": bool(meta.get("draft_cloud_last_action_download", False)),
            "draft_cloud_purchase_info": str(meta.get("draft_cloud_purchase_info") or ""),
            "draft_cloud_template_id": str(meta.get("draft_cloud_template_id") or ""),
            "draft_cloud_tutorial_info": str(meta.get("draft_cloud_tutorial_info") or ""),
            "draft_cloud_videocut_purchase_info": str(meta.get("draft_cloud_videocut_purchase_info") or ""),
            "draft_cover": os.path.join(exported_dir, "draft_cover.jpg").replace("\\", "/"),
            "draft_fold_path": exported_dir.replace("\\", "/"),
            "draft_id": str(meta.get("draft_id") or "").strip(),
            "draft_is_ai_shorts": bool(meta.get("draft_is_ai_shorts", False)),
            "draft_is_cloud_temp_draft": bool(meta.get("draft_is_cloud_temp_draft", False)),
            "draft_is_invisible": bool(meta.get("draft_is_invisible", False)),
            "draft_is_web_article_video": bool(meta.get("draft_is_web_article_video", False)),
            "draft_json_file": draft_content_path.replace("\\", "/"),
            "draft_name": str(meta.get("draft_name") or os.path.basename(exported_dir.rstrip("\\/"))),
            "draft_new_version": str(meta.get("draft_new_version") or ""),
            "draft_root_path": str(meta.get("draft_root_path") or os.path.dirname(exported_dir)),
            "draft_timeline_materials_size": draft_file_size,
            "draft_type": str(meta.get("draft_type") or ""),
            "draft_web_article_video_enter_from": str(meta.get("draft_web_article_video_enter_from") or ""),
            "streaming_edit_draft_ready": True,
            "tm_draft_cloud_completed": meta.get("tm_draft_cloud_completed") or "",
            "tm_draft_cloud_entry_id": int(meta.get("tm_draft_cloud_entry_id") or -1),
            "tm_draft_cloud_modified": int(meta.get("tm_draft_cloud_modified") or 0),
            "tm_draft_cloud_parent_entry_id": int(meta.get("tm_draft_cloud_parent_entry_id") or -1),
            "tm_draft_cloud_space_id": int(meta.get("tm_draft_cloud_space_id") or -1),
            "tm_draft_cloud_user_id": int(meta.get("tm_draft_cloud_user_id") or -1),
            "tm_draft_create": int(meta.get("tm_draft_create") or 0),
            "tm_draft_modified": int(meta.get("tm_draft_modified") or 0),
            "tm_draft_removed": int(meta.get("tm_draft_removed") or 0),
            "tm_duration": int(meta.get("tm_duration") or 0),
        }

    def _sync_root_meta_index(self, exported_dir: str, draft_content_path: str, meta: dict) -> None:
        if not meta:
            return
        draft_id = str(meta.get("draft_id") or "").strip()
        draft_fold_path = exported_dir.replace("\\", "/")
        draft_json_file = draft_content_path.replace("\\", "/")
        entry = self._build_root_meta_entry(meta, exported_dir, draft_content_path)
        for root_meta_path in self._candidate_root_meta_paths():
            payload = self._load_json_dict(root_meta_path)
            entries = payload.get("all_draft_store") or []
            if not isinstance(entries, list):
                entries = []
            filtered_entries = []
            for item in entries:
                if not isinstance(item, dict):
                    continue
                item_draft_id = str(item.get("draft_id") or "").strip()
                item_fold_path = str(item.get("draft_fold_path") or "").strip().replace("\\", "/")
                item_json_file = str(item.get("draft_json_file") or "").strip().replace("\\", "/")
                if draft_id and item_draft_id == draft_id:
                    continue
                if item_fold_path and item_fold_path == draft_fold_path:
                    continue
                if item_json_file and item_json_file == draft_json_file:
                    continue
                filtered_entries.append(item)
            filtered_entries.append(entry)
            filtered_entries.sort(
                key=lambda item: int(item.get("tm_draft_modified") or item.get("tm_draft_create") or 0),
                reverse=True,
            )
            payload["all_draft_store"] = filtered_entries
            payload["draft_ids"] = len(filtered_entries)
            payload["root_path"] = str(payload.get("root_path") or os.path.dirname(root_meta_path)).replace("\\", "/")
            self._write_json_dict(root_meta_path, payload)

    def _ensure_export_scaffold(self, exported_dir: str, draft_content_path: str) -> None:
        scaffold_root = self._get_draft_scaffold_path()
        if not scaffold_root:
            return

        top_level_entries = [
            "adjust_mask",
            "common_attachment",
            "materialResources",
            "matting",
            "qr_upload",
            "Resources",
            "smart_crop",
            "subdraft",
            "{01ecc63a-1a01-4cb1-9956-5b6889792879}",
            "{9e8b9f6b-522e-4432-bf0b-54e4cfafd6fe}",
            "{f65ab88d-5d29-4587-ad4a-75b9476d3447}",
            "{f9ca7292-5597-4f99-b7b0-f3fe171abe69}",
            "{fd4826c3-59a6-481d-8e62-ede163cf306d}",
            "attachment_editing.json",
            "attachment_pc_common.json",
            "draft_biz_config.json",
            "draft_settings",
            "draft_virtual_store.json",
            "performance_opt_info.json",
            "template.json",
            "timeline_layout.json",
        ]
        for name in top_level_entries:
            source_path = os.path.join(scaffold_root, name)
            if os.path.exists(source_path):
                self._copy_missing_entry(source_path, os.path.join(exported_dir, name))

        with open(draft_content_path, "rb") as handle:
            draft_content_bytes = handle.read()

        for mirror_name in ("draft_content.json.bak", "template-2.tmp"):
            with open(os.path.join(exported_dir, mirror_name), "wb") as handle:
                handle.write(draft_content_bytes)

        scaffold_cover = os.path.join(scaffold_root, "draft_cover.jpg")
        target_draft_cover = os.path.join(exported_dir, "draft_cover.jpg")
        if not os.path.isfile(target_draft_cover) and os.path.isfile(scaffold_cover):
            shutil.copy2(scaffold_cover, target_draft_cover)

        target_cover = os.path.join(exported_dir, "cover.jpg")
        if not os.path.isfile(target_cover):
            if os.path.isfile(target_draft_cover):
                shutil.copy2(target_draft_cover, target_cover)
            elif os.path.isfile(scaffold_cover):
                shutil.copy2(scaffold_cover, target_cover)

        scaffold_timelines_root = os.path.join(scaffold_root, "Timelines")
        target_timelines_root = os.path.join(exported_dir, "Timelines")
        if os.path.isdir(scaffold_timelines_root):
            self._copy_missing_entry(scaffold_timelines_root, target_timelines_root)
            timeline_dirs = [
                name
                for name in os.listdir(target_timelines_root)
                if os.path.isdir(os.path.join(target_timelines_root, name))
            ]
            if timeline_dirs:
                timeline_dir = os.path.join(target_timelines_root, timeline_dirs[0])
                for mirror_name in ("draft_content.json", "draft_content.json.bak", "template-2.tmp", "template.tmp"):
                    with open(os.path.join(timeline_dir, mirror_name), "wb") as handle:
                        handle.write(draft_content_bytes)
                timeline_cover = os.path.join(timeline_dir, "draft_cover.jpg")
                if not os.path.isfile(timeline_cover):
                    if os.path.isfile(target_draft_cover):
                        shutil.copy2(target_draft_cover, timeline_cover)
                    elif os.path.isfile(scaffold_cover):
                        shutil.copy2(scaffold_cover, timeline_cover)

    # -------------------------
    # Draft management
    # -------------------------
    def create_draft(self, draft_name: str, width: int = 1920, height: int = 1080, fps: int = 30) -> ServiceResult:
        try:
            self.config.validate()
            require_non_empty(draft_name, "draft_name")
        except Exception as e:
            return ServiceResult(False, str(e), code="validation_error")

        draft_id = str(uuid.uuid4())
        draft_path = os.path.join(self.config.save_path, draft_id)
        os.makedirs(draft_path, exist_ok=True)

        draft_data = {
            "draft_id": draft_id,
            "draft_name": draft_name,
            "width": width,
            "height": height,
            "fps": fps,
        }
        draft_json_path = os.path.join(draft_path, "draft.json")
        with open(draft_json_path, "w", encoding="utf-8") as f:
            json.dump(draft_data, f, ensure_ascii=False, indent=4)

        index_manager.add_draft_mapping(
            draft_id,
            {
                "draft_name": draft_name,
                "created_time": datetime.datetime.now().isoformat(),
                "width": width,
                "height": height,
                "fps": fps,
            },
        )

        return ServiceResult(True, "draft created", data=draft_data)

    def export_draft(self, draft_id: str, jianying_draft_path: Optional[str] = None) -> ServiceResult:
        try:
            self.config.validate()
            require_non_empty(draft_id, "draft_id")
        except Exception as e:
            return ServiceResult(False, str(e), code="validation_error")

        draft_data_path = os.path.join(self.config.save_path, draft_id)
        if not os.path.exists(draft_data_path):
            return ServiceResult(False, f"draft not found: {draft_id}", code="not_found")

        output_path = jianying_draft_path or self.config.output_path
        exporter = ExportDraft(output_path)
        result = exporter.export(draft_id)
        if not isinstance(result, dict):
            return ServiceResult(False, "export failed", code="export_failed")

        exported_name = str(result.get("draft_name") or "").strip()
        exported_root = str(result.get("output") or output_path or "").strip()
        exported_dir = os.path.join(exported_root, exported_name) if exported_root and exported_name else ""
        draft_content_path = os.path.join(exported_dir, "draft_content.json") if exported_dir else ""
        export_logs = result.get("export_logs", []) or []
        has_error_log = any(str((item or {}).get("level") or "").strip().lower() == "error" for item in export_logs if isinstance(item, dict))
        if not exported_dir or not os.path.isdir(exported_dir) or not os.path.isfile(draft_content_path):
            message = "export produced empty draft folder"
            if has_error_log:
                latest_error = next(
                    (
                        str((item or {}).get("message") or "").strip()
                        for item in reversed(export_logs)
                        if isinstance(item, dict) and str((item or {}).get("level") or "").strip().lower() == "error"
                    ),
                    "",
                )
                if latest_error:
                    message = latest_error
            return ServiceResult(
                False,
                message,
                code="export_failed",
                data={
                    "draft_id": draft_id,
                    "output": result.get("output"),
                    "draft_name": result.get("draft_name"),
                    "export_logs": export_logs,
                    "summary": result.get("summary", {}),
                },
            )

        agency_config_path = os.path.join(exported_dir, "draft_agency_config.json")
        if not os.path.isfile(agency_config_path):
            try:
                with open(agency_config_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "is_auto_agency_enabled": False,
                            "is_auto_agency_popup": False,
                            "is_single_agency_mode": False,
                            "marterials": None,
                            "use_converter": False,
                            "video_resolution": 720,
                        },
                        f,
                        ensure_ascii=False,
                    )
            except Exception as exc:
                return ServiceResult(
                    False,
                    f"draft_agency_config write failed: {exc}",
                    code="export_failed",
                    data={
                        "draft_id": draft_id,
                        "output": result.get("output"),
                        "draft_name": result.get("draft_name"),
                        "export_logs": export_logs,
                        "summary": result.get("summary", {}),
                    },
                )

        try:
            self._ensure_export_scaffold(exported_dir, draft_content_path)
        except Exception as exc:
            return ServiceResult(
                False,
                f"draft scaffold sync failed: {exc}",
                code="export_failed",
                data={
                    "draft_id": draft_id,
                    "output": result.get("output"),
                    "draft_name": result.get("draft_name"),
                    "export_logs": export_logs,
                    "summary": result.get("summary", {}),
                },
            )

        try:
            updated_meta = self._sync_exported_draft_meta(exported_dir, draft_content_path)
            self._sync_root_meta_index(exported_dir, draft_content_path, updated_meta)
        except Exception as exc:
            return ServiceResult(
                False,
                f"draft meta sync failed: {exc}",
                code="export_failed",
                data={
                    "draft_id": draft_id,
                    "output": result.get("output"),
                    "draft_name": result.get("draft_name"),
                    "export_logs": export_logs,
                    "summary": result.get("summary", {}),
                },
            )

        return ServiceResult(
            True,
            "export success",
            data={
                "draft_id": draft_id,
                "output": result.get("output"),
                "draft_name": result.get("draft_name"),
                "export_logs": result.get("export_logs", []),
                "summary": result.get("summary", {}),
            },
        )

    # -------------------------
    # Track management
    # -------------------------
    def create_track(self, draft_id: str, track_type: str, track_name: Optional[str] = None) -> ServiceResult:
        try:
            require_non_empty(draft_id, "draft_id")
            require_non_empty(track_type, "track_type")
        except Exception as e:
            return ServiceResult(False, str(e), code="validation_error")
        return from_tool_response(create_track_service(draft_id, track_type, track_name))

    # -------------------------
    # Video processing
    # -------------------------
    def add_video_segment(
        self,
        draft_id: str,
        material: str,
        target_timerange: str,
        source_timerange: Optional[str] = None,
        speed: Optional[float] = None,
        volume: float = 1.0,
        change_pitch: bool = False,
        clip_settings: Optional[Dict[str, Any]] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        try:
            require_non_empty(draft_id, "draft_id")
            require_path(material, "material")
            require_timerange(target_timerange)
        except Exception as e:
            return ServiceResult(False, str(e), code="validation_error")
        return from_tool_response(
            add_video_segment_service(
                draft_id=draft_id,
                material=material,
                target_timerange=target_timerange,
                source_timerange=source_timerange,
                speed=speed,
                volume=volume,
                change_pitch=change_pitch,
                clip_settings=clip_settings,
                track_name=track_name,
            )
        )

    def add_video_animation(
        self,
        draft_id: str,
        video_segment_id: str,
        animation_type: str,
        animation_name: str,
        duration: Optional[str] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(
            add_video_animation_service(
            draft_id,
            video_segment_id,
            animation_type,
            animation_name,
            duration,
            track_name,
        ))

    def add_video_transition(
        self,
        draft_id: str,
        video_segment_id: str,
        transition_type: str,
        duration: Optional[str] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(
            add_video_transition_service(
            draft_id,
            video_segment_id,
            transition_type,
            duration,
            track_name,
        ))

    def add_video_filter(
        self,
        draft_id: str,
        video_segment_id: str,
        filter_type: str,
        intensity: float = 100.0,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(add_video_filter_service(draft_id, video_segment_id, filter_type, intensity, track_name))

    def add_video_mask(
        self,
        draft_id: str,
        video_segment_id: str,
        mask_type: str,
        center_x: float = 0.0,
        center_y: float = 0.0,
        size: float = 0.5,
        rotation: float = 0.0,
        feather: float = 0.0,
        invert: bool = False,
        rect_width: Optional[float] = None,
        round_corner: Optional[float] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(
            add_video_mask_service(
            draft_id,
            video_segment_id,
            mask_type,
            center_x,
            center_y,
            size,
            rotation,
            feather,
            invert,
            rect_width,
            round_corner,
            track_name,
        ))

    def add_video_keyframe(
        self,
        draft_id: str,
        video_segment_id: str,
        property_name: str,
        time_offset: str,
        value: float,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(add_video_keyframe_service(draft_id, video_segment_id, property_name, time_offset, value, track_name))

    def add_video_background_filling(
        self,
        draft_id: str,
        video_segment_id: str,
        fill_type: str,
        blur: float = 0.0625,
        color: str = "#00000000",
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(
            add_video_background_filling_service(
            draft_id,
            video_segment_id,
            fill_type,
            blur,
            color,
            track_name,
        ))

    def add_video_effect(
        self,
        draft_id: str,
        video_segment_id: str,
        effect_type: str,
        params: Optional[List[Optional[float]]] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(add_video_effect_service(draft_id, video_segment_id, effect_type, params, track_name))

    # -------------------------
    # Audio processing
    # -------------------------
    def add_audio_segment(
        self,
        draft_id: str,
        material: str,
        target_timerange: str,
        source_timerange: Optional[str] = None,
        speed: Optional[float] = None,
        volume: float = 1.0,
        change_pitch: bool = False,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(
            add_audio_segment_service(
            draft_id,
            material,
            target_timerange,
            source_timerange,
            speed,
            volume,
            change_pitch,
            track_name,
        ))

    def add_audio_effect(
        self,
        draft_id: str,
        audio_segment_id: str,
        effect_type: str,
        effect_name: str,
        params: Optional[List[Optional[float]]] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(add_audio_effect_service(draft_id, audio_segment_id, effect_type, effect_name, params, track_name))

    def add_audio_fade(
        self,
        draft_id: str,
        audio_segment_id: str,
        in_duration: str,
        out_duration: str,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(add_audio_fade_service(draft_id, audio_segment_id, in_duration, out_duration, track_name))

    def add_audio_keyframe(
        self,
        draft_id: str,
        audio_segment_id: str,
        time_offset: str,
        volume: float,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(add_audio_keyframe_service(draft_id, audio_segment_id, time_offset, volume, track_name))

    # -------------------------
    # Text processing
    # -------------------------
    def add_text_segment(
        self,
        draft_id: str,
        text: str,
        timerange: str,
        font: Optional[str] = None,
        style: Optional[Dict[str, Any]] = None,
        clip_settings: Optional[Dict[str, Any]] = None,
        border: Optional[Dict[str, Any]] = None,
        background: Optional[Dict[str, Any]] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(
            add_text_segment_service(
            draft_id,
            text,
            timerange,
            font,
            style,
            clip_settings,
            border,
            background,
            track_name,
        ))

    def add_text_animation(
        self,
        draft_id: str,
        text_segment_id: str,
        animation_type: str,
        animation_name: str,
        duration: Optional[str] = None,
        track_name: Optional[str] = None,
    ) -> ServiceResult:
        return from_tool_response(
            add_text_animation_service(
            draft_id,
            text_segment_id,
            animation_type,
            animation_name,
            duration,
            track_name,
        ))

    def add_text_bubble(self, draft_id: str, text_segment_id: str, effect_id: str, resource_id: str) -> ServiceResult:
        try:
            text_segment = TextSegment(draft_id, text_segment_id=text_segment_id)
            ok = text_segment.add_bubble(effect_id=effect_id, resource_id=resource_id)
            if not ok:
                return ServiceResult(False, "add bubble failed", code="bubble_failed")
            return ServiceResult(
                True,
                "add bubble success",
                data={
                    "draft_id": draft_id,
                    "text_segment_id": text_segment_id,
                    "effect_id": effect_id,
                    "resource_id": resource_id,
                },
            )
        except Exception as e:
            return ServiceResult(False, f"add bubble failed: {str(e)}", code="bubble_failed")

    def add_text_effect(self, draft_id: str, text_segment_id: str, effect_id: str) -> ServiceResult:
        try:
            text_segment = TextSegment(draft_id, text_segment_id=text_segment_id)
            ok = text_segment.add_effect(effect_id=effect_id)
            if not ok:
                return ServiceResult(False, "add effect failed", code="effect_failed")
            return ServiceResult(
                True,
                "add effect success",
                data={
                    "draft_id": draft_id,
                    "text_segment_id": text_segment_id,
                    "effect_id": effect_id,
                },
            )
        except Exception as e:
            return ServiceResult(False, f"add effect failed: {str(e)}", code="effect_failed")

    # -------------------------
    # Utility
    # -------------------------
    def parse_media_info(self, media_path: str) -> ServiceResult:
        parser = MediaParser()
        info = parser.parse_media_info(media_path)
        if not info:
            return ServiceResult(False, "parse media failed", code="parse_failed")
        return ServiceResult(True, "parse media success", data={"media_info": info})

    def find_effects_by_type(
        self,
        effect_type: str,
        is_vip: Optional[bool] = None,
        limit: Optional[int] = None,
        keyword: Optional[str] = None,
    ) -> ServiceResult:
        manager = JianYingResourceManager()
        try:
            effects = manager.find_by_type(effect_type=effect_type, is_vip=is_vip, limit=limit, keyword=keyword)
        except Exception as e:
            return ServiceResult(False, f"find effects failed: {str(e)}", code="find_failed")

        return ServiceResult(True, f"found {len(effects)} effects", data={"effects": effects, "effect_type": effect_type})
