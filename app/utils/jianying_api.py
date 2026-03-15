import json
import os
import uuid
from app.utils.helpers import pick_random_material
from app.utils.JianYingApi.Drafts import Create_New_Drafts

def create_draft_from_json(json_path):
    """
    根据 JSON 模板动态生成剪映草稿（使用真实API）
    :param json_path: 模板 JSON 文件路径
    :return: 草稿名称
    """
    # 读取 JSON 模板
    with open(json_path, 'r', encoding='utf-8') as f:
        template = json.load(f)

    # 生成草稿名称（不含路径，Create_New_Drafts 会基于当前工作目录的 blanks/ 创建）
    draft_name = f"草稿_{os.path.basename(json_path)}"
    draft_base_name = os.path.splitext(draft_name)[0]

    # 创建新草稿，返回 Projects 实例
    # Create_New_Drafts 会在当前目录下的 blanks 复制模板，然后返回 Projects(Path=新草稿路径)
    projects = Create_New_Drafts(draft_base_name)  # 注意：Create_New_Drafts 接受草稿文件夹名称，会自动创建并填充 blanks

    # 创建视频轨道（用于素材）
    video_track = projects.Content.NewTrack(TrackType="video")

    current_time = 0  # 时间单位：微秒（注意：Drafts.py 中时间单位为微秒，但 JSON 中的 duration 是秒，需转换）
    for shot in template.get("shots", []):
        duration_sec = shot.get("duration", 2)
        duration_us = duration_sec * 1_000_000  # 转换为微秒
        text = shot.get("text", "")

        # 随机选取一张素材图片
        material_path = pick_random_material()
        if not material_path:
            print("素材不足，停止生成")
            break

        # 生成素材唯一 ID
        material_id = str(uuid.uuid4())
        material_name = os.path.basename(material_path)

        # 将素材导入剪映素材库（可选，但 AddMaterial 需要先导入？）
        # 注意：根据 Drafts.py，Meta.Import2Lib 可以将素材导入媒体库，但 AddMaterial 可以直接添加？
        # 为了简单，我们直接使用 AddMaterial，不导入库，可能需要调整。
        # 这里先假设 AddMaterial 可以直接添加素材到项目素材列表。
        projects.Content.AddMaterial(
            Mtype="videos",
            Content={
                "id": material_id,
                "material_name": material_name,
                "path": material_path.replace("\\", "/"),
                "type": "video",
                "extra_info": material_name,
                "metetype": "video"  # 可能需要这个字段
            }
        )

        # 将素材添加到视频轨道
        segment_id = str(uuid.uuid4())
        projects.Content.Add2Track(
            Track_id=video_track["id"],
            Content={
                "id": segment_id,
                "material_id": material_id,
                "visible": True,
                "volume": 1,
                "source_timerange": {
                    "duration": duration_us,
                    "start": 0
                },
                "target_timerange": {
                    "duration": duration_us,
                    "start": current_time
                }
            }
        )

        # 如果有文字，需要添加文字（暂略，待后续实现）
        if text:
            print(f"文字 '{text}' 将在后续版本添加")

        current_time += duration_us

    # 保存草稿
    projects.Save()
    return draft_base_name