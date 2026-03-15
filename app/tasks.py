import os
import shutil
import uuid
import json
import random
import logging
from rq import get_current_job
from app import create_app
from app.extensions import db
from app.models.task import Task
from app.models.template_model import TemplateModel
from app.models.task_effect_log import TaskEffectLog
from app.utils.helpers import get_drafts_folder

# MCP 路径当前不匹配实际目录结构，避免误用导致退回字符串替换
MCP_AVAILABLE = False

def _build_file_index(root_path):
    index = {}
    for root, _dirs, files in os.walk(root_path):
        for fname in files:
            key = fname.lower()
            if key not in index:
                index[key] = os.path.join(root, fname)
    return index

def _update_material_paths(draft_data, file_index):
    materials = draft_data.get('materials', {})
    for media_type in ('videos', 'images', 'audios'):
        items = materials.get(media_type, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            path = item.get('path') or item.get('file_path')
            if not path:
                continue
            fname = os.path.basename(path)
            if not fname:
                continue
            new_path = file_index.get(fname.lower())
            if new_path:
                item['path'] = new_path
                if 'file_path' in item:
                    item['file_path'] = new_path

def _update_material_paths_from_user_files(draft_data, user_files, material_map):
    if not user_files:
        return
    materials = draft_data.get('materials', {})
    for media_type in ('videos', 'images', 'audios'):
        items = materials.get(media_type, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get('id')
            material_name = item.get('material_name')
            path = item.get('path') or item.get('file_path')
            fname = None
            if material_name:
                fname = material_name
            elif path:
                fname = os.path.basename(path)

            new_path = None
            if fname and fname.lower() in user_files:
                new_path = user_files[fname.lower()]
            elif item_id and material_map:
                for name, mid in material_map.items():
                    if mid == item_id and name.lower() in user_files:
                        new_path = user_files[name.lower()]
                        break

            if new_path:
                item['path'] = new_path
                if 'file_path' in item:
                    item['file_path'] = new_path

def _safe_update_style_ranges(styles, total_len):
def _extract_template_runtime_info(template_path):
    materials = []
    material_map = {}
    texts_info = []
    if not template_path:
        return materials, material_map, texts_info
    draft_content = os.path.join(template_path, 'draft_content.json')
    if not os.path.exists(draft_content):
        return materials, material_map, texts_info
    try:
        with open(draft_content, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return materials, material_map, texts_info

    mats = data.get('materials', {})
    for media_type in ('videos', 'images', 'audios'):
        for item in mats.get(media_type, []) or []:
            if not isinstance(item, dict):
                continue
            path = item.get('path') or item.get('file_path') or ''
            mid = item.get('id')
            if path:
                name = os.path.basename(path)
                if name and name not in materials:
                    materials.append(name)
                if name and mid:
                    material_map[name] = mid

    for item in mats.get('texts', []) or []:
        if not isinstance(item, dict):
            continue
        default_text = item.get('recognize_text') or item.get('content') or ''
        texts_info.append({
            'index': len(texts_info),
            'default': default_text,
            'material_id': item.get('id')
        })

    return materials, material_map, texts_info

    if not styles:
        return
    for style in styles:
        if not isinstance(style, dict):
            continue
        rng = style.get('range')
        if not (isinstance(rng, list) and len(rng) == 2):
            continue
        start = min(max(int(rng[0]), 0), total_len)
        end = min(max(int(rng[1]), 0), total_len)
        if end < start:
            end = start
        style['range'] = [start, end]
    # 确保最后一个范围覆盖新文本长度
    for style in reversed(styles):
        rng = style.get('range')
        if isinstance(rng, list) and len(rng) == 2:
            style['range'] = [min(rng[0], total_len), total_len]
            break

def _replace_texts_with_style(draft_data, texts_input, texts_info):
    materials = draft_data.get('materials', {})
    text_materials = materials.get('texts', [])
    if not isinstance(text_materials, list) or not text_materials:
        return 0

    # 从文本轨道提取 material_id 顺序（更可靠的索引映射）
    track_material_ids = []
    for track in draft_data.get('tracks', []):
        if track.get('type') != 'text':
            continue
        for seg in track.get('segments', []):
            mid = seg.get('material_id')
            if mid:
                track_material_ids.append(mid)

    # 预构建 material_id -> text_material
    text_by_id = {}
    for item in text_materials:
        if isinstance(item, dict) and item.get('id'):
            text_by_id[item['id']] = item

    replaced = 0
    for user_text in texts_input:
        if not isinstance(user_text, dict):
            continue
        idx = user_text.get('index')
        contents = user_text.get('contents') or []
        new_text = contents[0] if contents else ''
        if new_text is None:
            continue
        new_text = str(new_text)

        target_item = None
        material_id = None
        if isinstance(texts_info, list) and idx is not None and 0 <= idx < len(texts_info):
            info = texts_info[idx]
            if isinstance(info, dict):
                material_id = info.get('material_id')
        if material_id and material_id in text_by_id:
            target_item = text_by_id[material_id]
        elif idx is not None and 0 <= idx < len(track_material_ids):
            track_mid = track_material_ids[idx]
            target_item = text_by_id.get(track_mid)
        elif idx is not None and 0 <= idx < len(text_materials):
            target_item = text_materials[idx]

        if not isinstance(target_item, dict):
            continue

        content_str = target_item.get('content')
        if content_str:
            try:
                content_json = json.loads(content_str)
                content_json['text'] = new_text
                styles = content_json.get('styles', [])
                _safe_update_style_ranges(styles, len(new_text))
                target_item['content'] = json.dumps(content_json, ensure_ascii=False)
            except Exception:
                # 如果 content 解析失败，至少更新 recognize_text
                pass

        target_item['recognize_text'] = new_text
        target_item['_vf_new_text'] = new_text
        replaced += 1

    return replaced

def _update_subtitle_taskinfo(draft_data):
    updated = 0
    text_by_task = {}
    for txt in draft_data.get('materials', {}).get('texts', []):
        if isinstance(txt, dict):
            task_id = txt.get('recognize_task_id')
            new_text = txt.get('_vf_new_text')
            if task_id and new_text is not None:
                text_by_task[task_id] = new_text

    config = draft_data.get('config', {})
    subtitle_taskinfo = config.get('subtitle_taskinfo', [])
    if not isinstance(subtitle_taskinfo, list):
        return 0

    for item in subtitle_taskinfo:
        if not isinstance(item, dict):
            continue
        task_id = item.get('id')
        if task_id in text_by_task:
            try:
                content = item.get('content')
                if not content:
                    continue
                content_json = json.loads(content)
                utterances = content_json.get('utterances', [])
                if utterances:
                    for u in utterances:
                        u['text'] = text_by_task[task_id]
                content_json['utterances'] = utterances
                item['content'] = json.dumps(content_json, ensure_ascii=False)
                updated += 1
            except Exception:
                continue
    return updated

def _clear_temp_text_marks(draft_data):
    for txt in draft_data.get('materials', {}).get('texts', []):
        if isinstance(txt, dict) and '_vf_new_text' in txt:
            del txt['_vf_new_text']

def _update_track_text_segments(draft_data):
    updated = 0
    text_by_id = {}
    for txt in draft_data.get('materials', {}).get('texts', []):
        if isinstance(txt, dict) and txt.get('id') and txt.get('_vf_new_text') is not None:
            text_by_id[txt['id']] = txt['_vf_new_text']

    for track in draft_data.get('tracks', []):
        if track.get('type') != 'text':
            continue
        for seg in track.get('segments', []):
            mid = seg.get('material_id')
            if not mid or mid not in text_by_id:
                continue
            new_text = text_by_id[mid]
            if seg.get('content'):
                try:
                    content_json = json.loads(seg.get('content'))
                    if isinstance(content_json, dict):
                        content_json['text'] = new_text
                        styles = content_json.get('styles', [])
                        _safe_update_style_ranges(styles, len(new_text))
                        seg['content'] = json.dumps(content_json, ensure_ascii=False)
                        updated += 1
                except Exception:
                    continue
    return updated

def update_task_meta(meta):
    job = get_current_job()
    if job:
        task = Task.query.get(job.id)
        if task:
            task.progress = json.dumps(meta)
            db.session.commit()


def handle_generate_success(job, connection, result, *args, **kwargs):
    try:
        user_id = job.args[-1]
    except Exception:
        user_id = None
    if not user_id:
        return
    if isinstance(result, dict) and result.get('ok') is False:
        return
    try:
        app = create_app()
        with app.app_context():
            from app.services.user_quota_service import deduct_quota
            deduct_quota(user_id, amount=1)
    except Exception as e:
        logging.error(f"quota deduct failed: {e}")

def generate_video_task(template_id, materials_root, texts_input, batch_count,
                        replace_materials=True, replace_texts=True,
                        replace_type='both', replace_mode='order', audio_enabled=False,
                        effects_config=None, duo_config=None, user_id=None):
    app = create_app()
    with app.app_context():
        job = get_current_job()
        task_id = job.id
        task = Task.query.get(task_id)
        if task:
            task.status = 'started'
            db.session.commit()

        try:
            template = TemplateModel.query.get(template_id)
            if not template:
                raise Exception("模板不存在")
            template_path = template.template_path

            # 素材映射（用于素材替换）
            material_map = material_map or {}
            all_material_names = list(material_map.keys())

            def filter_by_type(fname):
                ext = os.path.splitext(fname)[1].lower()
                is_img = ext in ('.jpg','.jpeg','.png','.bmp','.gif','.webp')
                is_vid = ext in ('.mp4','.mov','.avi','.mkv','.flv','.wmv','.m4v')
                if replace_type == 'image':
                    return is_img
                elif replace_type == 'video':
                    return is_vid
                else:
                    return is_img or is_vid
            material_names = [f for f in all_material_names if filter_by_type(f)]

            # 原文字列表（从模板配置中获取，必须是纯字符串列表）
            raw_texts = texts_info or []
            original_texts = []
            if raw_texts:
                if isinstance(raw_texts[0], dict):
                    original_texts = [item.get('default', '') for item in raw_texts]
                else:
                    original_texts = raw_texts

            update_task_meta({'progress': '正在读取素材文件夹...'})
            drafts_folder = get_drafts_folder()
            if not drafts_folder:
                raise Exception("草稿路径未配置")

            sets = []
            try:
                for item in os.listdir(materials_root):
                    item_path = os.path.join(materials_root, item)
                    if os.path.isdir(item_path):
                        sets.append(item_path)
            except Exception as e:
                raise Exception(f"无法访问素材路径 {materials_root}: {str(e)}")
            if not sets:
                sets = [materials_root]

            generated = 0
            for i in range(min(batch_count, len(sets))):
                set_folder = sets[i]

                draft_name = f"task_{uuid.uuid4().hex[:8]}"
                new_draft_path = os.path.join(drafts_folder, draft_name)
                if os.path.exists(new_draft_path):
                    shutil.rmtree(new_draft_path)

                update_task_meta({'progress': f'正在复制模板 ({i+1}/{batch_count})...'})
                shutil.copytree(template_path, new_draft_path)

                draft_content_path = os.path.join(new_draft_path, 'draft_content.json')
                if not os.path.exists(draft_content_path):
                    raise Exception(f"新草稿缺少 draft_content.json")

                # 预先修正素材路径，避免仍指向旧草稿目录
                try:
                    file_index = _build_file_index(new_draft_path)
                    with open(draft_content_path, 'r', encoding='utf-8') as f:
                        draft_data = json.load(f)
                    _update_material_paths(draft_data, file_index)
                    with open(draft_content_path, 'w', encoding='utf-8') as f:
                        json.dump(draft_data, f, ensure_ascii=False)
                except Exception as e:
                    print(f"[DEBUG] 修正素材路径失败: {e}")

                # ---------- 素材替换：直接覆盖同名文件 ----------
                user_files = {}
                if replace_materials and material_names:
                    if replace_mode == 'random':
                        selected_names = random.sample(material_names, len(material_names))
                    else:
                        selected_names = material_names

                    for fname in selected_names:
                        user_file = None
                        for root, dirs, files in os.walk(set_folder):
                            if fname in files:
                                user_file = os.path.join(root, fname)
                                break
                        if not user_file:
                            print(f"[DEBUG] 未找到用户文件 {fname}")
                            update_task_meta({'progress': f'警告：未找到文件 {fname}'})
                            continue
                        user_files[fname.lower()] = user_file

                        # 在新草稿中查找同名文件
                        target_file = None
                        for root, dirs, files in os.walk(new_draft_path):
                            if fname in files:
                                target_file = os.path.join(root, fname)
                                break
                        if target_file:
                            shutil.copy2(user_file, target_file)
                            print(f"[DEBUG] 覆盖素材: {user_file} -> {target_file}")
                            update_task_meta({'progress': f'替换素材: {fname}'})
                        else:
                            # 如果找不到同名文件，尝试用内部ID
                            internal_id = material_map.get(fname)
                            if internal_id:
                                for root, dirs, files in os.walk(new_draft_path):
                                    if internal_id in files:
                                        target_file = os.path.join(root, internal_id)
                                        shutil.copy2(user_file, target_file)
                                        print(f"[DEBUG] 覆盖素材(内部ID): {user_file} -> {target_file}")
                                        update_task_meta({'progress': f'替换素材: {fname}'})
                                        break
                                else:
                                    print(f"[DEBUG] 未找到素材 {fname} 的目标文件")
                            else:
                                print(f"[DEBUG] 未找到素材 {fname} 的目标文件")

                # 根据用户素材更新 JSON 路径，避免外链丢失
                if replace_materials and user_files:
                    try:
                        with open(draft_content_path, 'r', encoding='utf-8') as f:
                            draft_data = json.load(f)
                        _update_material_paths_from_user_files(
                            draft_data,
                            user_files,
                            material_map
                        )
                        with open(draft_content_path, 'w', encoding='utf-8') as f:
                            json.dump(draft_data, f, ensure_ascii=False)
                    except Exception as e:
                        print(f"[DEBUG] 更新素材路径失败: {e}")

                # ---------- 文字替换：结构化更新，保留样式 ----------
                if replace_texts and texts_input:
                    with open(draft_content_path, 'r', encoding='utf-8') as f:
                        draft_data = json.load(f)
                    replaced_count = _replace_texts_with_style(
                        draft_data,
                        texts_input,
                        texts_info or []
                    )
                    subtitle_updated = _update_subtitle_taskinfo(draft_data)
                    track_updated = _update_track_text_segments(draft_data)
                    _clear_temp_text_marks(draft_data)
                    if replaced_count:
                        with open(draft_content_path, 'w', encoding='utf-8') as f:
                            json.dump(draft_data, f, ensure_ascii=False)
                        print(f"[DEBUG] 文字替换完成，共替换 {replaced_count} 段，字幕更新 {subtitle_updated}，轨道更新 {track_updated}")
                        update_task_meta({'progress': f'文字替换完成，共替换 {replaced_count} 段'})

                # 附加音频
                if audio_enabled:
                    audio_dir = os.path.join(new_draft_path, 'audio')
                    os.makedirs(audio_dir, exist_ok=True)
                    for fname in os.listdir(set_folder):
                        if fname.lower().endswith(('.mp3','.wav','.m4a')):
                            src = os.path.join(set_folder, fname)
                            dst = os.path.join(audio_dir, fname)
                            shutil.copy2(src, dst)
                            update_task_meta({'progress': f'附加音频: {fname}'})

                # 高级效果（MCP）导出
                # MCP effects apply
                if effects_config or duo_config:
                    try:
                        from app.services.jianying_service import JianYingService
                        from app.utils.jianying_mcp.utils.media_parser import MediaParser
                        from app.utils.jianying_mcp.utils.time_format import parse_start_end_format
                        svc = JianYingService()
                        update_task_meta({'progress': '正在应用高级效果...'})
                        summary = _apply_mcp_effects(new_draft_path, effects_config, svc, duo_config)
                        if summary:
                            update_task_meta({'progress': 'MCP effects applied', 'effects_summary': summary})
                            try:
                                log = TaskEffectLog(task_id=task_id, summary=json.dumps(summary, ensure_ascii=False))
                                db.session.add(log)
                                db.session.commit()
                            except Exception as e:
                                print(f"[DEBUG] MCP effects log failed: {e}")
                    except Exception as e:
                        print(f"[DEBUG] MCP 高级效果应用失败: {e}")

                generated += 1
                update_task_meta({'progress': f'已完成 {generated}/{batch_count} 个草稿'})

            update_task_meta({'progress': '全部完成'})
            if task:
                task.status = 'finished'
                db.session.commit()

            return {'ok': True, 'message': '批量生成成功', 'generated': generated}

        except Exception as e:
            if task:
                task.status = 'failed'
                task.error_msg = str(e)
                db.session.commit()
            raise e


def _apply_mcp_effects(draft_path, effects_config, svc, duo_config=None):
    """
    基于 MCP 导出流程生成带效果的新草稿（实验性）。
    注意：该流程会重建轨道与素材，可能丢失部分模板样式。
    """
    import json
    import os
    import uuid
    import shutil
    import subprocess

    summary = {"applied": [], "warnings": []}

    draft_content = os.path.join(draft_path, 'draft_content.json')
    if not os.path.exists(draft_content):
        summary["warnings"].append("draft_content.json not found")
        return summary

    with open(draft_content, 'r', encoding='utf-8') as f:
        data = json.load(f)

    effects_config = effects_config or {}

    # if only duo preprocess/text styles, avoid rebuild to preserve template
    if effects_config.get('video') is None and effects_config.get('audio') is None and effects_config.get('text') is None:
        effects_config = {}
    # 构建 MCP 草稿
    draft_id = uuid.uuid4().hex
    svc.create_draft(draft_name=f"mcp_{draft_id}", width=data.get("canvas_config", {}).get("width", 1080),
                     height=data.get("canvas_config", {}).get("height", 1920),
                     fps=data.get("fps", 30))

    # create tracks based on original draft order
    track_name_by_index = {}
    overlay_track_name = None
    for idx, track in enumerate(data.get("tracks", [])):
        ttype = track.get("type")
        if ttype not in ("video", "audio", "text"):
            continue
        raw_name = track.get("name") or track.get("track_name") or f"{ttype}_{idx}"
        resp = svc.create_track(draft_id, ttype, raw_name)
        if resp and getattr(resp, "ok", False) and resp.data and resp.data.get("track_name"):
            track_name_by_index[idx] = resp.data.get("track_name")
        else:
            track_name_by_index[idx] = raw_name

    # build maps
    materials = data.get("materials", {})
    video_mats = {m.get("id"): m for m in materials.get("videos", [])}
    audio_mats = {m.get("id"): m for m in materials.get("audios", [])}
    text_mats = {m.get("id"): m for m in materials.get("texts", [])}

    video_segment_ids = []
    audio_segment_ids = []
    text_segment_ids = []

    video_segment_track = {}
    audio_segment_track = {}
    text_segment_track = {}

    # segments (preserve track order and basic clip settings)
    def _trange_str(tr):
        if not isinstance(tr, dict):
            return None
        start = float(tr.get("start", 0)) / 1_000_000
        duration = float(tr.get("duration", 0)) / 1_000_000
        return f"{start}s-{duration}s"

    for idx, track in enumerate(data.get("tracks", [])):
        ttype = track.get("type")
        if ttype not in ("video", "audio", "text"):
            continue
        track_name = track_name_by_index.get(idx)
        for seg in track.get("segments", []):
            mid = seg.get("material_id")
            if ttype == "video":
                mat = video_mats.get(mid)
                if not mat:
                    continue
                path = mat.get("path") or mat.get("file_path")
                if not path:
                    continue
                target_timerange = _trange_str(seg.get("target_timerange", {}))
                if not target_timerange:
                    continue
                source_timerange = _trange_str(seg.get("source_timerange", {}))
                clip_settings = seg.get("clip_settings") or seg.get("clip")
                speed = seg.get("speed")
                volume = seg.get("volume", 1.0)
                change_pitch = seg.get("change_pitch", False)
                resp = svc.add_video_segment(
                    draft_id,
                    path,
                    target_timerange,
                    source_timerange=source_timerange,
                    speed=speed,
                    volume=volume,
                    change_pitch=change_pitch,
                    clip_settings=clip_settings if isinstance(clip_settings, dict) else None,
                    track_name=track_name,
                )
                if resp.ok and resp.data:
                    video_segment_ids.append(resp.data.get("video_segment_id"))
                    video_segment_track[len(video_segment_ids)-1] = track_name
            elif ttype == "audio":
                mat = audio_mats.get(mid)
                if not mat:
                    continue
                path = mat.get("path") or mat.get("file_path")
                if not path:
                    continue
                target_timerange = _trange_str(seg.get("target_timerange", {}))
                if not target_timerange:
                    continue
                source_timerange = _trange_str(seg.get("source_timerange", {}))
                speed = seg.get("speed")
                volume = seg.get("volume", 1.0)
                change_pitch = seg.get("change_pitch", False)
                resp = svc.add_audio_segment(
                    draft_id,
                    path,
                    target_timerange,
                    source_timerange=source_timerange,
                    speed=speed,
                    volume=volume,
                    change_pitch=change_pitch,
                    track_name=track_name,
                )
                if resp.ok and resp.data:
                    audio_segment_ids.append(resp.data.get("audio_segment_id"))
                    audio_segment_track[len(audio_segment_ids)-1] = track_name
            else:
                mat = text_mats.get(mid)
                if not mat:
                    continue
                content = mat.get("recognize_text") or ""
                target_timerange = _trange_str(seg.get("target_timerange", {}))
                if not target_timerange:
                    continue
                resp = svc.add_text_segment(
                    draft_id,
                    content,
                    target_timerange,
                    track_name=track_name,
                )
                if resp.ok and resp.data:
                    text_segment_ids.append(resp.data.get("text_segment_id"))
                    text_segment_track[len(text_segment_ids)-1] = track_name


    def _normalize_list(val):
        if val is None:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return [val]
        return []

    def _ids_by_track(ids, item, track_name_map):
        tname = item.get('track')
        if not tname:
            return _ids_by_index(ids, item)
        selected = []
        for i, sid in enumerate(ids):
            if track_name_map.get(i) == tname:
                selected.append(sid)
        if 'indexes' in item and isinstance(item['indexes'], list):
            return [selected[i] for i in item['indexes'] if 0 <= i < len(selected)]
        if 'index' in item and isinstance(item['index'], int):
            i = item['index']
            return [selected[i]] if 0 <= i < len(selected) else []
        return selected

    def _ids_by_index(ids, item):
        if "indexes" in item and isinstance(item["indexes"], list):
            return [ids[i] for i in item["indexes"] if 0 <= i < len(ids)]
        if "index" in item:
            i = item["index"]
            if isinstance(i, int) and 0 <= i < len(ids):
                return [ids[i]]
        return ids

    video_cfg = effects_config.get("video", {})
    text_cfg = effects_config.get("text", {})
    audio_cfg = effects_config.get("audio", {})
    duo_cfg = {}
    if duo_config:
        try:
            from app.services.duo_video_service import DuoVideoService
            duo_svc = DuoVideoService()
            duo_mapped = duo_svc.build_effects_config(duo_config)
            # merge duo into effects_config
            for k in ("filters", "effects", "animations", "transitions", "masks", "keyframes", "background"):
                if duo_mapped["video"].get(k):
                    video_cfg.setdefault(k, [])
                    video_cfg[k].extend(duo_mapped["video"].get(k))
            for k in ("animations", "bubbles", "effects"):
                if duo_mapped["text"].get(k):
                    text_cfg.setdefault(k, [])
                    text_cfg[k].extend(duo_mapped["text"].get(k))
            for k in ("effects", "fades", "keyframes"):
                if duo_mapped["audio"].get(k):
                    audio_cfg.setdefault(k, [])
                    audio_cfg[k].extend(duo_mapped["audio"].get(k))
            duo_cfg = duo_mapped.get("_duo", {})
        except Exception as e:
            summary["warnings"].append(f"duo config map failed: {e}")

    existing_tracks = set(track_name_by_index.values())
    has_mcp_effects = any([
        video_cfg.get('filters'), video_cfg.get('effects'), video_cfg.get('animations'), video_cfg.get('transitions'), video_cfg.get('masks'), video_cfg.get('background'), video_cfg.get('keyframes'),
        text_cfg.get('animations'), text_cfg.get('bubbles'), text_cfg.get('effects'),
        audio_cfg.get('effects'), audio_cfg.get('fades'), audio_cfg.get('keyframes')
    ])
    has_duo_pre = any([duo_cfg.get('green_screen'), duo_cfg.get('reverse'), duo_cfg.get('lut'), duo_cfg.get('text_styles')])
    if not has_mcp_effects and has_duo_pre and not duo_cfg.get('stickers'):
        _apply_duo_preprocess(duo_cfg, data)
        _apply_text_char_styles(duo_cfg.get('text_styles'))
        summary['applied'].append('duo_preprocess_only')
        return summary

    if duo_cfg.get('stickers'):
        # create overlay track for stickers
        resp = svc.create_track(draft_id, 'video', 'sticker_overlay')
        if resp and getattr(resp, 'ok', False) and resp.data and resp.data.get('track_name'):
            overlay_track_name = resp.data.get('track_name')
        else:
            overlay_track_name = 'sticker_overlay'

    # stickers overlay
    if duo_cfg.get('stickers') and overlay_track_name:
        try:
            from app.services.duo_video_service import DuoVideoService
            duo_svc = DuoVideoService()
        except Exception:
            duo_svc = None
        for item in duo_cfg.get('stickers') or []:
            path = item.get('path')
            url = item.get('url')
            if not path and url and duo_svc:
                path = duo_svc.download_resource(url)
            if not path:
                summary['warnings'].append('sticker asset missing')
                continue
            timerange = item.get('timerange') or '0s-3s'
            clip_settings = item.get('clip_settings') if isinstance(item.get('clip_settings'), dict) else None
            track = item.get('track') or overlay_track_name
            if track and track not in existing_tracks:
                resp_track = svc.create_track(draft_id, 'video', track)
                if resp_track and getattr(resp_track, 'ok', False) and resp_track.data and resp_track.data.get('track_name'):
                    track = resp_track.data.get('track_name')
                existing_tracks.add(track)
            resp = svc.add_video_segment(draft_id, path, timerange, clip_settings=clip_settings, track_name=track)
            _record(resp, 'sticker')

    def _dedupe(items):
        seen = set()
        result = []
        for item in items or []:
            try:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            except Exception:
                key = str(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    for k in ("filters", "effects", "animations", "transitions", "masks", "background", "keyframes"):
        if isinstance(video_cfg.get(k), list):
            video_cfg[k] = _dedupe(video_cfg.get(k))
    for k in ("animations", "bubbles", "effects"):
        if isinstance(text_cfg.get(k), list):
            text_cfg[k] = _dedupe(text_cfg.get(k))
    for k in ("effects", "fades", "keyframes"):
        if isinstance(audio_cfg.get(k), list):
            audio_cfg[k] = _dedupe(audio_cfg.get(k))

    def _apply_text_char_styles(text_styles):
        if not text_styles:
            return
        try:
            with open(draft_content, 'r', encoding='utf-8') as f:
                local_data = json.load(f)
        except Exception:
            return
        text_mats_local = {m.get('id'): m for m in local_data.get('materials', {}).get('texts', []) if isinstance(m, dict)}
        for item in text_styles:
            idx = item.get('index')
            styles = item.get('styles')
            if idx is None or not isinstance(styles, list):
                continue
            target = None
            if isinstance(idx, int):
                track_ids = []
                for tr in local_data.get('tracks', []):
                    if tr.get('type') != 'text':
                        continue
                    for seg in tr.get('segments', []):
                        if seg.get('material_id'):
                            track_ids.append(seg.get('material_id'))
                if 0 <= idx < len(track_ids):
                    target = text_mats_local.get(track_ids[idx])
            if not target:
                continue
            content = target.get('content')
            if not content:
                continue
            try:
                content_json = json.loads(content)
            except Exception:
                continue
            content_json['styles'] = styles
            target['content'] = json.dumps(content_json, ensure_ascii=False)
        try:
            with open(draft_content, 'w', encoding='utf-8') as f:
                json.dump(local_data, f, ensure_ascii=False)
        except Exception:
            return

    def _apply_duo_preprocess(duo_cfg, draft_data):
        if not duo_cfg:
            return
        ffmpeg = os.getenv('FFMPEG_PATH') or shutil.which('ffmpeg')
        if not ffmpeg:
            if duo_cfg.get('reverse'):
                summary['warnings'].append('reverse requested: ffmpeg not found')
            if duo_cfg.get('lut'):
                summary['warnings'].append('lut requested: ffmpeg not found')
            if duo_cfg.get('green_screen'):
                summary['warnings'].append('green_screen requested: ffmpeg not found')
            return

        def _material_by_index(video_index):
            track_ids = []
            for tr in draft_data.get('tracks', []):
                if tr.get('type') != 'video':
                    continue
                for seg in tr.get('segments', []):
                    if seg.get('material_id'):
                        track_ids.append(seg.get('material_id'))
            if isinstance(video_index, int) and 0 <= video_index < len(track_ids):
                return track_ids[video_index]
            return None

        def _replace_material_path(mat_id, new_path):
            for m in draft_data.get('materials', {}).get('videos', []):
                if m.get('id') == mat_id:
                    m['path'] = new_path
                    if 'file_path' in m:
                        m['file_path'] = new_path
                    return True
            return False

        def _run(cmd):
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return True
            except Exception as e:
                summary['warnings'].append(f'ffmpeg failed: {e}')
                return False

        # reverse
        for item in duo_cfg.get('reverse') or []:
            idx = item.get('video_index')
            mid = item.get('material_id') or _material_by_index(idx)
            if not mid:
                summary['warnings'].append('reverse: target not found')
                continue
            m = next((x for x in draft_data.get('materials', {}).get('videos', []) if x.get('id') == mid), None)
            if not m:
                continue
            src = m.get('path') or m.get('file_path')
            if not src:
                continue
            out_path = os.path.join(os.path.dirname(src), f'rev_{os.path.basename(src)}')
            cmd = [ffmpeg, '-y', '-i', src, '-vf', 'reverse', '-af', 'areverse', out_path]
            if _run(cmd):
                _replace_material_path(mid, out_path)
                summary['applied'].append('reverse')

        # lut
        for item in duo_cfg.get('lut') or []:
            idx = item.get('video_index')
            mid = item.get('material_id') or _material_by_index(idx)
            lut_path = item.get('lut_path')
            if not mid or not lut_path:
                summary['warnings'].append('lut: target or lut missing')
                continue
            m = next((x for x in draft_data.get('materials', {}).get('videos', []) if x.get('id') == mid), None)
            if not m:
                continue
            src = m.get('path') or m.get('file_path')
            if not src:
                continue
            out_path = os.path.join(os.path.dirname(src), f'lut_{os.path.basename(src)}')
            cmd = [ffmpeg, '-y', '-i', src, '-vf', f'lut3d={lut_path}', out_path]
            if _run(cmd):
                _replace_material_path(mid, out_path)
                summary['applied'].append('lut')

        # green screen (chroma key)
        for item in duo_cfg.get('green_screen') or []:
            idx = item.get('video_index')
            mid = item.get('material_id') or _material_by_index(idx)
            bg_path = item.get('bg_path')
            key_color = item.get('key_color', '0x00FF00')
            similarity = item.get('tolerance', 0.2)
            blend = item.get('feather', 0.1)
            if not mid or not bg_path:
                summary['warnings'].append('green_screen: target or background missing')
                continue
            m = next((x for x in draft_data.get('materials', {}).get('videos', []) if x.get('id') == mid), None)
            if not m:
                continue
            src = m.get('path') or m.get('file_path')
            if not src:
                continue
            out_path = os.path.join(os.path.dirname(src), f'ck_{os.path.basename(src)}')
            filter_complex = f"[0:v]chromakey={key_color}:{similarity}:{blend}[ck];[1:v][ck]overlay=format=auto"
            cmd = [ffmpeg, '-y', '-i', src, '-i', bg_path, '-filter_complex', filter_complex, out_path]
            if _run(cmd):
                _replace_material_path(mid, out_path)
                summary['applied'].append('green_screen')

        try:
            with open(draft_content, 'w', encoding='utf-8') as f:
                json.dump(draft_data, f, ensure_ascii=False)
        except Exception as e:
            summary['warnings'].append(f'draft_content write failed: {e}')



    def _record(result, label):
        try:
            if result and getattr(result, "ok", False):
                summary["applied"].append(label)
            else:
                summary["warnings"].append(f"failed: {label}")
        except Exception:
            summary["warnings"].append(f"failed: {label}")

    if not video_segment_ids and (video_cfg.get("filters") or video_cfg.get("effects") or video_cfg.get("animations") or video_cfg.get("transitions") or video_cfg.get("masks") or video_cfg.get("background") or video_cfg.get("keyframes")):
        summary["warnings"].append("no video segments to apply video effects")
    if not audio_segment_ids and (audio_cfg.get("effects") or audio_cfg.get("fades") or audio_cfg.get("keyframes")):
        summary["warnings"].append("no audio segments to apply audio effects")
    if not text_segment_ids and (text_cfg.get("animations") or text_cfg.get("bubbles") or text_cfg.get("effects")):
        summary["warnings"].append("no text segments to apply text effects")

    # duo preprocess (best-effort)
    _apply_duo_preprocess(duo_cfg, data)
    _apply_text_char_styles(duo_cfg.get('text_styles'))

    # video filters
    for item in _normalize_list(video_cfg.get("filters")):
        ftype = item.get("type")
        intensity = float(item.get("intensity", 80))
        if not ftype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_filter(draft_id, sid, ftype, intensity), f"video_filter:{ftype}")

    # video effects
    for item in _normalize_list(video_cfg.get("effects")):
        etype = item.get("type")
        params = item.get("params")
        if not etype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_effect(draft_id, sid, etype, params), f"video_effect:{etype}")

    # video animations
    for item in _normalize_list(video_cfg.get("animations")):
        atype = item.get("type")
        name = item.get("name")
        duration = item.get("duration")
        if not (atype and name):
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_animation(draft_id, sid, atype, name, duration), f"video_anim:{atype}:{name}")

    # video transitions
    for item in _normalize_list(video_cfg.get("transitions")):
        ttype = item.get("type")
        duration = item.get("duration")
        if not ttype:
            continue
        targets = _ids_by_track(video_segment_ids, item, video_segment_track)
        # default: from second segment
        if targets == video_segment_ids:
            targets = video_segment_ids[1:]
        for sid in targets:
            _record(svc.add_video_transition(draft_id, sid, ttype, duration), f"transition:{ttype}")

    # video masks
    for item in _normalize_list(video_cfg.get("masks")):
        mtype = item.get("type")
        if not mtype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_mask(
                draft_id,
                sid,
                mtype,
                item.get("center_x", 0.0),
                item.get("center_y", 0.0),
                item.get("size", 0.5),
                item.get("rotation", 0.0),
                item.get("feather", 0.0),
                item.get("invert", False),
                item.get("rect_width"),
                item.get("round_corner"),
            ), f"mask:{mtype}")

    # video background filling
    for item in _normalize_list(video_cfg.get("background")):
        ftype = item.get("type")
        if not ftype:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_background_filling(
                draft_id,
                sid,
                ftype,
                item.get("blur", 0.0625),
                item.get("color", "#00000000"),
            ), f"background:{ftype}")

    # video keyframes
    for item in _normalize_list(video_cfg.get("keyframes")):
        prop = item.get("property")
        time_offset = item.get("time")
        value = item.get("value")
        if prop is None or time_offset is None or value is None:
            continue
        for sid in _ids_by_track(video_segment_ids, item, video_segment_track):
            _record(svc.add_video_keyframe(draft_id, sid, prop, time_offset, value), f"video_keyframe:{prop}@{time_offset}")

    # text animations
    for item in _normalize_list(text_cfg.get("animations")):
        atype = item.get("type")
        name = item.get("name")
        duration = item.get("duration")
        if not (atype and name):
            continue
        for sid in _ids_by_track(text_segment_ids, item, text_segment_track):
            _record(svc.add_text_animation(draft_id, sid, atype, name, duration), f"text_anim:{atype}:{name}")

    # text bubbles
    for item in _normalize_list(text_cfg.get("bubbles")):
        effect_id = item.get("effect_id")
        resource_id = item.get("resource_id")
        if not (effect_id and resource_id):
            continue
        for sid in _ids_by_track(text_segment_ids, item, text_segment_track):
            _record(svc.add_text_bubble(draft_id, sid, effect_id, resource_id), f"text_bubble:{effect_id}")

    # text effects
    for item in _normalize_list(text_cfg.get("effects")):
        effect_id = item.get("effect_id")
        if not effect_id:
            continue
        for sid in _ids_by_track(text_segment_ids, item, text_segment_track):
            _record(svc.add_text_effect(draft_id, sid, effect_id), f"text_effect:{effect_id}")

    # audio effects
    for item in _normalize_list(audio_cfg.get("effects")):
        etype = item.get("type")
        name = item.get("name")
        params = item.get("params")
        if not (etype and name):
            continue
        for sid in _ids_by_track(audio_segment_ids, item, audio_segment_track):
            _record(svc.add_audio_effect(draft_id, sid, etype, name, params), f"audio_effect:{etype}:{name}")

    # audio fades
    for item in _normalize_list(audio_cfg.get("fades")):
        in_dur = item.get("in")
        out_dur = item.get("out")
        if not (in_dur and out_dur):
            continue
        for sid in _ids_by_track(audio_segment_ids, item, audio_segment_track):
            _record(svc.add_audio_fade(draft_id, sid, in_dur, out_dur), "audio_fade")

    # audio keyframes
    for item in _normalize_list(audio_cfg.get("keyframes")):
        time_offset = item.get("time")
        volume = item.get("volume")
        if time_offset is None or volume is None:
            continue
        for sid in _ids_by_track(audio_segment_ids, item, audio_segment_track):
            _record(svc.add_audio_keyframe(draft_id, sid, time_offset, volume), f"audio_keyframe@{time_offset}")

    # export
    output_path = os.getenv("OUTPUT_PATH")
    if output_path:
        result = svc.export_draft(draft_id, jianying_draft_path=output_path)
        if result.ok and result.data:
            print(f"[DEBUG] MCP 效果草稿已导出: {result.data.get('draft_name')}")
            summary["applied"].append(f"export:{result.data.get('draft_name')}")
        else:
            summary["warnings"].append("export failed")

    return summary
