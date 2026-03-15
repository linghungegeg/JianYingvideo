import uuid
import json
from copy import deepcopy
from typing import Optional, Tuple, List, Dict, Any, Union, Literal

class Timerange:
    def __init__(self, start: int, duration: int):
        self.start = start
        self.duration = duration
    @property
    def end(self) -> int:
        return self.start + self.duration
    def export_json(self) -> Dict[str, int]:
        return {"start": self.start, "duration": self.duration}

class BaseSegment:
    def __init__(self, material_id: str, target_timerange: Timerange):
        self.segment_id = uuid.uuid4().hex
        self.material_id = material_id
        self.target_timerange = target_timerange
        self.common_keyframes = []

class Speed:
    def __init__(self, speed: float):
        self.global_id = uuid.uuid4().hex
        self.speed = speed
    def export_json(self) -> Dict[str, Any]:
        return {"id": self.global_id, "mode": 0, "speed": self.speed, "type": "speed"}

class ClipSettings:
    def __init__(self, *, alpha=1.0, flip_horizontal=False, flip_vertical=False,
                 rotation=0.0, scale_x=1.0, scale_y=1.0, transform_x=0.0, transform_y=0.0):
        self.alpha = alpha
        self.flip_horizontal = flip_horizontal
        self.flip_vertical = flip_vertical
        self.rotation = rotation
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.transform_x = transform_x
        self.transform_y = transform_y
    def export_json(self) -> Dict[str, Any]:
        return {
            "alpha": self.alpha,
            "flip": {"horizontal": self.flip_horizontal, "vertical": self.flip_vertical},
            "rotation": self.rotation,
            "scale": {"x": self.scale_x, "y": self.scale_y},
            "transform": {"x": self.transform_x, "y": self.transform_y}
        }

class MediaSegment(BaseSegment):
    def __init__(self, material_id: str, source_timerange: Optional[Timerange],
                 target_timerange: Timerange, speed: float, volume: float, change_pitch: bool):
        super().__init__(material_id, target_timerange)
        self.source_timerange = source_timerange
        self.speed = Speed(speed)
        self.volume = volume
        self.change_pitch = change_pitch
        self.extra_material_refs = [self.speed.global_id]

class VisualSegment(MediaSegment):
    def __init__(self, material_id: str, source_timerange: Optional[Timerange],
                 target_timerange: Timerange, speed: float, volume: float, change_pitch: bool,
                 *, clip_settings: Optional[ClipSettings] = None):
        super().__init__(material_id, source_timerange, target_timerange, speed, volume, change_pitch)
        self.clip_settings = clip_settings if clip_settings else ClipSettings()
        self.uniform_scale = True
        self.animations_instance = None

class TextStyle:
    def __init__(self, *, size: float = 6.0, bold: bool = False, italic: bool = False, underline: bool = False,
                 color: Tuple[float, float, float] = (1.0, 1.0, 1.0), alpha: float = 1.0,
                 align: Literal[0, 1, 2] = 0, vertical: bool = False,
                 letter_spacing: int = 0, line_spacing: int = 0,
                 auto_wrapping: bool = False, max_line_width: float = 0.82):
        self.size = size
        self.bold = bold
        self.italic = italic
        self.underline = underline
        self.color = color
        self.alpha = alpha
        self.align = align
        self.vertical = vertical
        self.letter_spacing = letter_spacing
        self.line_spacing = line_spacing
        self.auto_wrapping = auto_wrapping
        self.max_line_width = max_line_width

class TextBorder:
    def __init__(self, *, alpha: float = 1.0, color: Tuple[float, float, float] = (0.0, 0.0, 0.0), width: float = 40.0):
        self.alpha = alpha
        self.color = color
        self.width = width / 100.0 * 0.2
    def export_json(self) -> Dict[str, Any]:
        return {
            "content": {
                "solid": {
                    "alpha": self.alpha,
                    "color": list(self.color),
                }
            },
            "width": self.width
        }

class TextBackground:
    def __init__(self, *, color: str, style: Literal[1, 2] = 1, alpha: float = 1.0, round_radius: float = 0.0,
                 height: float = 0.14, width: float = 0.14,
                 horizontal_offset: float = 0.5, vertical_offset: float = 0.5):
        self.style = style
        self.alpha = alpha
        self.color = color
        self.round_radius = round_radius
        self.height = height
        self.width = width
        self.horizontal_offset = horizontal_offset * 2 - 1
        self.vertical_offset = vertical_offset * 2 - 1
    def export_json(self) -> Dict[str, Any]:
        return {
            "background_style": self.style,
            "background_color": self.color,
            "background_alpha": self.alpha,
            "background_round_radius": self.round_radius,
            "background_height": self.height,
            "background_width": self.width,
            "background_horizontal_offset": self.horizontal_offset,
            "background_vertical_offset": self.vertical_offset,
        }

class TextBubble:
    def __init__(self, effect_id: str, resource_id: str):
        self.global_id = uuid.uuid4().hex
        self.effect_id = effect_id
        self.resource_id = resource_id
    def export_json(self) -> Dict[str, Any]:
        return {
            "apply_target_type": 0,
            "effect_id": self.effect_id,
            "id": self.global_id,
            "resource_id": self.resource_id,
            "type": "text_shape",
            "value": 1.0,
        }

class TextEffect(TextBubble):
    def export_json(self) -> Dict[str, Any]:
        ret = super().export_json()
        ret["type"] = "text_effect"
        ret["source_platform"] = 1
        return ret

class TextSegment(VisualSegment):
    def __init__(self, text: str, timerange: Timerange, *,
                 font: Optional[str] = None,
                 style: Optional[TextStyle] = None,
                 clip_settings: Optional[ClipSettings] = None,
                 border: Optional[TextBorder] = None,
                 background: Optional[TextBackground] = None):
        super().__init__(uuid.uuid4().hex, None, timerange, 1.0, 1.0, False, clip_settings=clip_settings)
        self.text = text
        self.font = font
        self.style = style or TextStyle()
        self.border = border
        self.background = background
        self.bubble = None
        self.effect = None

    @classmethod
    def create_from_template(cls, text: str, timerange: Timerange, template: "TextSegment") -> "TextSegment":
        new_segment = cls(text, timerange,
                          style=deepcopy(template.style),
                          clip_settings=deepcopy(template.clip_settings),
                          border=deepcopy(template.border),
                          background=deepcopy(template.background))
        new_segment.font = deepcopy(template.font)
        if template.animations_instance:
            new_segment.animations_instance = deepcopy(template.animations_instance)
            new_segment.animations_instance.animation_id = uuid.uuid4().hex
            new_segment.extra_material_refs.append(new_segment.animations_instance.animation_id)
        if template.bubble:
            new_segment.add_bubble(template.bubble.effect_id, template.bubble.resource_id)
        if template.effect:
            new_segment.add_effect(template.effect.effect_id)
        return new_segment

    def add_bubble(self, effect_id: str, resource_id: str) -> "TextSegment":
        self.bubble = TextBubble(effect_id, resource_id)
        self.extra_material_refs.append(self.bubble.global_id)
        return self

    def add_effect(self, effect_id: str) -> "TextSegment":
        self.effect = TextEffect(effect_id, effect_id)
        self.extra_material_refs.append(self.effect.global_id)
        return self

    def export_material(self) -> Dict[str, Any]:
        check_flag = 7
        if self.border: check_flag |= 8
        if self.background: check_flag |= 16
        content_json = {
            "styles": [{
                "fill": {
                    "alpha": 1.0,
                    "content": {
                        "render_type": "solid",
                        "solid": {"alpha": 1.0, "color": list(self.style.color)}
                    }
                },
                "range": [0, len(self.text)],
                "size": self.style.size,
                "bold": self.style.bold,
                "italic": self.style.italic,
                "underline": self.style.underline,
                "strokes": [self.border.export_json()] if self.border else []
            }],
            "text": self.text
        }
        ret = {
            "id": self.material_id,
            "content": json.dumps(content_json, ensure_ascii=False),
            "typesetting": int(self.style.vertical),
            "alignment": self.style.align,
            "letter_spacing": self.style.letter_spacing * 0.05,
            "line_spacing": 0.02 + self.style.line_spacing * 0.05,
            "line_feed": 1,
            "line_max_width": self.style.max_line_width,
            "force_apply_line_max_width": False,
            "check_flag": check_flag,
            "type": "subtitle" if self.style.auto_wrapping else "text",
            "global_alpha": self.style.alpha,
        }
        if self.background:
            ret.update(self.background.export_json())
        return ret