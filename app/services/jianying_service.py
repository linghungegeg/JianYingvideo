import datetime
import json
import logging
import os
import importlib
import uuid
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

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
            runtime_save_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "user_data", "mcp_cache")
            )
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
