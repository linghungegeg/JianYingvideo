import os
import shutil
import uuid
import json
import random
import logging
import threading

try:
    from rq import get_current_job
except Exception:  # pragma: no cover - local desktop runtime can run without RQ
    def get_current_job():
        return None
from app import create_app
from app.extensions import db
from app.models.task import Task
from app.models.template_model import TemplateModel
from app.models.task_effect_log import TaskEffectLog
from app.utils.helpers import get_drafts_folder
from app.utils.ffmpeg_utils import find_ffmpeg

# MCP 路径当前不匹配实际目录结构，避免误用导致退回字符串替换
MCP_AVAILABLE = False
_LOCAL_TASK_CONTEXT = threading.local()

def _build_file_index(root_path):
    index = {}
    for root, _dirs, files in os.walk(root_path):
        for fname in files:
            key = fname.lower()
            if key not in index:
                index[key] = os.path.join(root, fname)
    return index

def _list_media_files(root_path, replace_type):
    if not root_path or not os.path.exists(root_path):
        return []
    exts_img = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    exts_vid = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v')
    exts_aud = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')
    exts = exts_img + exts_vid + exts_aud
    files = []
    for root, _dirs, fnames in os.walk(root_path):
        for fname in fnames:
            ext = os.path.splitext(fname)[1].lower()
            if replace_type == 'image' and ext not in exts_img:
                continue
            if replace_type == 'video' and ext not in exts_vid:
                continue
            if replace_type == 'audio' and ext not in exts_aud:
                continue
            if replace_type == 'both' and ext not in exts:
                continue
            files.append(os.path.join(root, fname))
    return files

def _list_subfolders(root_path):
    if not root_path or not os.path.exists(root_path):
        return []
    folders = []
    for name in os.listdir(root_path):
        p = os.path.join(root_path, name)
        if os.path.isdir(p):
            folders.append(p)
    folders.sort()
    return folders

def _normalize_name(name):
    return os.path.splitext(name or '')[0].strip().lower()

def _build_partition_folder_map(root_path):
    folders = _list_subfolders(root_path)
    mapping = {}
    for folder in folders:
        key = _normalize_name(os.path.basename(folder))
        if key and key not in mapping:
            mapping[key] = folder
    return mapping

def _pick_from_list(files, mode, seed_index):
    if not files:
        return None
    if mode == 'random':
        return random.choice(files)
    return files[seed_index % len(files)]

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
    if not isinstance(styles, list) or total_len is None:
        return
    for style in styles:
        if not isinstance(style, dict):
            continue
        if isinstance(style.get('range'), list) and len(style['range']) == 2:
            start, end = style['range']
            try:
                start = max(0, int(start))
                end = max(0, int(end))
            except Exception:
                continue
            start = min(start, total_len)
            end = min(end, total_len)
            if end < start:
                end = start
            style['range'] = [start, end]
        if isinstance(style.get('ranges'), list):
            fixed = []
            for r in style['ranges']:
                if not isinstance(r, list) or len(r) != 2:
                    continue
                try:
                    start = max(0, int(r[0]))
                    end = max(0, int(r[1]))
                except Exception:
                    continue
                start = min(start, total_len)
                end = min(end, total_len)
                if end < start:
                    end = start
                fixed.append([start, end])
            style['ranges'] = fixed
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

def update_task_meta(meta, task_id=None):
    resolved_task_id = task_id
    if not resolved_task_id:
        resolved_task_id = getattr(_LOCAL_TASK_CONTEXT, "task_id", None)
    if not resolved_task_id:
        job = get_current_job()
        if job:
            resolved_task_id = job.id
    if resolved_task_id:
        task = Task.query.get(resolved_task_id)
        if task:
            task.progress = json.dumps(meta)
            db.session.commit()


def _resp_ok(resp):
    if resp is None:
        return False
    if hasattr(resp, "ok"):
        try:
            return bool(resp.ok)
        except Exception:
            return False
    if hasattr(resp, "success"):
        try:
            return bool(resp.success)
        except Exception:
            return False
    return False


def _resp_data(resp):
    if resp is None:
        return {}
    data = getattr(resp, "data", None)
    return data if isinstance(data, dict) else {}


def handle_generate_success(job, connection, result, *args, **kwargs):
    user_id = None
    try:
        if getattr(job, "args", None):
            # Batch jobs append template_path as the last positional arg,
            # while user_id is the argument right before it.
            if len(job.args) >= 2 and isinstance(job.args[-2], int):
                user_id = job.args[-2]
            elif isinstance(job.args[-1], int):
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
                        replace_audios=False,
                        replace_type='both', replace_mode='order', replace_strategy='group',
                        audio_enabled=False, audio_root=None, export_enabled=False, export_path=None, export_format=None,
                        export_resolution=None, export_fps=None,
                        effects_config=None, duo_config=None, user_id=None, template_path=None,
                        task_id_override=None):
    app = create_app()
    with app.app_context():
        job = get_current_job()
        task_id = task_id_override or (job.id if job else None)
        _LOCAL_TASK_CONTEXT.task_id = task_id
        task = Task.query.get(task_id)
        if task:
            task.status = 'started'
            db.session.commit()
        try:
            if not template_path:
                template = TemplateModel.query.get(template_id)
                if not template:
                    raise Exception("legacy template not found")

                template_path = template.template_path

            materials, material_map, texts_info = _extract_template_runtime_info(template_path)

            # 素材映射（用于素材替换）
            all_material_names = list(material_map.keys())

            def filter_by_type(fname):
                ext = os.path.splitext(fname)[1].lower()
                is_img = ext in ('.jpg','.jpeg','.png','.bmp','.gif','.webp')
                is_vid = ext in ('.mp4','.mov','.avi','.mkv','.flv','.wmv','.m4v')
                is_aud = ext in ('.mp3','.wav','.m4a','.aac','.ogg','.flac')
                if replace_type == 'image':
                    return is_img
                elif replace_type == 'video':
                    return is_vid
                elif replace_type == 'audio':
                    return is_aud
                else:
                    return is_img or is_vid or is_aud
            material_names = []
            for fname in all_material_names:
                ext = os.path.splitext(fname)[1].lower()
                is_audio = ext in ('.mp3','.wav','.m4a','.aac','.ogg','.flac')
                if is_audio and not replace_audios:
                    continue
                if not is_audio and not replace_materials:
                    continue
                if filter_by_type(fname):
                    material_names.append(fname)

            # 原文字列表（从模板配置中获取，必须是纯字符串列表）
            raw_texts = texts_info or []
            original_texts = []
            if raw_texts:
                if isinstance(raw_texts[0], dict):
                    original_texts = [item.get('default', '') for item in raw_texts]
                else:
                    original_texts = raw_texts
            update_task_meta({'progress': 'reading material files...'})
            drafts_folder = get_drafts_folder()
            if not drafts_folder:
                raise Exception("drafts folder is not configured")


            folder_cache = {}
            pool_files = []
            group_folders = []
            partition_map = {}
            if replace_strategy == 'mix':
                pool_files = _list_media_files(materials_root, replace_type)
            elif replace_strategy == 'partition':
                partition_map = _build_partition_folder_map(materials_root)
            else:
                group_folders = _list_subfolders(materials_root)

            generated = 0

            for i in range(batch_count):
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

                # ---------- 素材替换 ----------
                user_files = {}
                if replace_materials and material_names:
                    for idx, fname in enumerate(material_names):
                        user_file = None
                        if replace_strategy == 'mix':
                            user_file = _pick_from_list(pool_files, replace_mode, i + idx)
                        elif replace_strategy == 'partition':
                            folder = partition_map.get(_normalize_name(fname))
                            if folder:
                                files = folder_cache.get(folder)
                                if files is None:
                                    files = _list_media_files(folder, replace_type)
                                    folder_cache[folder] = files
                                user_file = _pick_from_list(files, replace_mode, i)
                        else:
                            if not group_folders:
                                if not pool_files:
                                    pool_files = _list_media_files(materials_root, replace_type)
                                user_file = _pick_from_list(pool_files, replace_mode, i + idx)
                            elif idx < len(group_folders):
                                folder = group_folders[idx]
                                files = folder_cache.get(folder)
                                if files is None:
                                    files = _list_media_files(folder, replace_type)
                                    folder_cache[folder] = files
                                user_file = _pick_from_list(files, replace_mode, i)

                        if not user_file:
                            print(f"[DEBUG] 未找到素材文件: {fname}")
                            update_task_meta({'progress': f'素材缺失: {fname}'})
                            continue
                        user_files[fname.lower()] = user_file

                        target_file = None
                        for root, dirs, files in os.walk(new_draft_path):
                            if fname in files:
                                target_file = os.path.join(root, fname)
                                break
                        if target_file:
                            shutil.copy2(user_file, target_file)
                            print(f"[DEBUG] 替换素材: {user_file} -> {target_file}")
                            update_task_meta({'progress': f'替换素材: {fname}'})
                        else:
                            internal_id = material_map.get(fname)
                            if internal_id:
                                for root, dirs, files in os.walk(new_draft_path):
                                    if internal_id in files:
                                        target_file = os.path.join(root, internal_id)
                                        shutil.copy2(user_file, target_file)
                                        print(f"[DEBUG] 替换素材(内部ID): {user_file} -> {target_file}")
                                        update_task_meta({'progress': f'替换素材: {fname}'})
                                        break
                                else:
                                    print(f"[DEBUG] 未找到目标文件: {fname}")
                            else:
                                print(f"[DEBUG] 未找到目标文件: {fname}")

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
                    audio_source_root = audio_root or materials_root
                    for root, _dirs, files in os.walk(audio_source_root):
                        for fname in files:
                            if fname.lower().endswith(('.mp3','.wav','.m4a')):
                                src = os.path.join(root, fname)
                                dst = os.path.join(audio_dir, fname)
                                shutil.copy2(src, dst)
                                update_task_meta({'progress': f'复制音频: {fname}'})

                # 高级效果（MCP）导出
                if export_enabled and export_path:
                    os.environ["OUTPUT_PATH"] = export_path
                # MCP effects apply
                if effects_config or duo_config or export_enabled:
                    try:
                        from app.services.jianying_service import JianYingService
                        from app.utils.jianying_mcp.utils.media_parser import MediaParser
                        from app.utils.jianying_mcp.utils.time_format import parse_start_end_format
                        svc = JianYingService()
                        update_task_meta({'progress': '正在应用高级效果...'})
                        summary = _apply_mcp_effects(
                            new_draft_path,
                            effects_config or {},
                            svc,
                            duo_config,
                            export_format=export_format,
                            export_resolution=export_resolution,
                            export_fps=export_fps,
                        )
                        if summary:
                            update_task_meta({'progress': 'MCP effects applied', 'effects_summary': summary})
                            try:
                                log = TaskEffectLog(task_id=task_id, summary=json.dumps(summary, ensure_ascii=False))
                                db.session.add(log)
                                db.session.commit()
                            except Exception as e:
                                print(f"[DEBUG] MCP effects log failed: {e}")
                    except Exception as e:
                        print(f"[DEBUG] MCP effects apply failed: {e}")

                generated += 1
                update_task_meta({'progress': f'completed {generated}/{batch_count} drafts'})

            update_task_meta({'progress': 'all completed'})
            if task:
                task.status = 'finished'
                db.session.commit()
            if user_id and not job:
                try:
                    from app.services.user_quota_service import deduct_quota
                    deduct_quota(user_id, amount=1)
                except Exception as quota_error:
                    logging.error(f"quota deduct failed: {quota_error}")

            return {'ok': True, 'message': 'batch generation completed', 'generated': generated}

        except Exception as e:
            if task:
                task.status = 'failed'
                task.error_msg = str(e)
                db.session.commit()
            raise e
        finally:
            if hasattr(_LOCAL_TASK_CONTEXT, "task_id"):
                delattr(_LOCAL_TASK_CONTEXT, "task_id")


def _apply_mcp_effects(draft_path, effects_config, svc, duo_config=None,
                       export_format=None, export_resolution=None, export_fps=None):
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
    fmt = export_format if export_format in ("mp4", "mov") else None
    draft_name = f"mcp_{draft_id}{'_' + fmt if fmt else ''}"
    canvas = data.get("canvas_config", {}) or {}
    base_w = canvas.get("width", 1080)
    base_h = canvas.get("height", 1920)
    landscape = base_w >= base_h
    if export_resolution in ("720p", "1080p", "4k"):
        if export_resolution == "720p":
            target_w, target_h = (1280, 720) if landscape else (720, 1280)
        elif export_resolution == "1080p":
            target_w, target_h = (1920, 1080) if landscape else (1080, 1920)
        else:  # 4k
            target_w, target_h = (3840, 2160) if landscape else (2160, 3840)
    else:
        target_w, target_h = base_w, base_h

    target_fps = data.get("fps", 30)
    if export_fps is not None:
        try:
            fps_int = int(export_fps)
            if fps_int > 0:
                target_fps = fps_int
        except Exception:
            pass

    create_resp = svc.create_draft(
        draft_name=draft_name,
        width=target_w,
        height=target_h,
        fps=target_fps,
    )
    if not create_resp or not getattr(create_resp, "ok", False):
        raise RuntimeError(getattr(create_resp, "message", None) or "create draft failed")
    created_draft_id = ((getattr(create_resp, "data", None) or {}).get("draft_id") or "").strip()
    if not created_draft_id:
        raise RuntimeError("create draft returned empty draft_id")

    draft_id = created_draft_id
    summary["draft_id"] = draft_id
    summary["draft_name"] = draft_name
    if fmt:
        summary["export_format"] = fmt

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

    micro_cfg = (effects_config.get("video") or {}).get("micro_adjust") or {}
    if micro_cfg.get("enabled") is False:
        micro_cfg = {}
    micro_indexes = set()
    if isinstance(micro_cfg.get("indexes"), list):
        micro_indexes = {i for i in micro_cfg.get("indexes") if isinstance(i, int) and i >= 0}
    micro_applied = False
    video_segment_meta = []

    def _rand_between(low, high):
        try:
            low = float(low)
            high = float(high)
        except Exception:
            return None
        if low > high:
            low, high = high, low
        return random.uniform(low, high)

    def _duration_from_tr(tr):
        if not isinstance(tr, dict):
            return None
        try:
            return float(tr.get("duration", 0)) / 1_000_000
        except Exception:
            return None

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
                seg_index = len(video_segment_ids)
                target_timerange = _trange_str(seg.get("target_timerange", {}))
                if not target_timerange:
                    continue
                source_timerange = _trange_str(seg.get("source_timerange", {}))
                clip_settings = seg.get("clip_settings") or seg.get("clip")
                speed = seg.get("speed")
                volume = seg.get("volume", 1.0)
                change_pitch = seg.get("change_pitch", False)

                apply_micro = bool(micro_cfg) and (not micro_indexes or seg_index in micro_indexes)
                if apply_micro:
                    speed_cfg = micro_cfg.get("speed") or {}
                    rand_speed = _rand_between(speed_cfg.get("min"), speed_cfg.get("max"))
                    if rand_speed:
                        base_speed = float(speed) if speed is not None else 1.0
                        speed = max(0.1, base_speed * rand_speed)
                        micro_applied = True

                    clip_map = dict(clip_settings) if isinstance(clip_settings, dict) else {}
                    transform_cfg = micro_cfg.get("transform") or {}
                    rand_scale = _rand_between(transform_cfg.get("scale_min"), transform_cfg.get("scale_max"))
                    if rand_scale:
                        base_sx = float(clip_map.get("scale_x", 1.0) or 1.0)
                        base_sy = float(clip_map.get("scale_y", 1.0) or 1.0)
                        clip_map["scale_x"] = base_sx * rand_scale
                        clip_map["scale_y"] = base_sy * rand_scale
                        micro_applied = True
                    pos_x = transform_cfg.get("pos_x")
                    try:
                        pos_x_val = float(pos_x)
                    except Exception:
                        pos_x_val = None
                    if pos_x_val is not None:
                        offset_x = _rand_between(-abs(pos_x_val), abs(pos_x_val))
                        if offset_x is not None:
                            base_x = float(clip_map.get("transform_x", 0.0) or 0.0)
                            clip_map["transform_x"] = base_x + offset_x
                            micro_applied = True
                    pos_y = transform_cfg.get("pos_y")
                    try:
                        pos_y_val = float(pos_y)
                    except Exception:
                        pos_y_val = None
                    if pos_y_val is not None:
                        offset_y = _rand_between(-abs(pos_y_val), abs(pos_y_val))
                        if offset_y is not None:
                            base_y = float(clip_map.get("transform_y", 0.0) or 0.0)
                            clip_map["transform_y"] = base_y + offset_y
                            micro_applied = True
                    rot_range = transform_cfg.get("rotation")
                    try:
                        rot_val = float(rot_range)
                    except Exception:
                        rot_val = None
                    if rot_val is not None:
                        offset_r = _rand_between(-abs(rot_val), abs(rot_val))
                        if offset_r is not None:
                            base_r = float(clip_map.get("rotation", 0.0) or 0.0)
                            clip_map["rotation"] = base_r + offset_r
                            micro_applied = True

                    mirror_cfg = micro_cfg.get("mirror") or {}
                    if mirror_cfg.get("horizontal"):
                        clip_map["flip_horizontal"] = random.choice([True, False])
                        micro_applied = True
                    if mirror_cfg.get("vertical"):
                        clip_map["flip_vertical"] = random.choice([True, False])
                        micro_applied = True

                    clip_settings = clip_map if clip_map else clip_settings

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
                resp_data = _resp_data(resp)
                if _resp_ok(resp) and resp_data:
                    video_segment_ids.append(resp_data.get("video_segment_id"))
                    video_segment_track[len(video_segment_ids)-1] = track_name
                    video_segment_meta.append({
                        "duration": _duration_from_tr(seg.get("target_timerange", {})),
                        "track": track_name,
                        "apply_micro": apply_micro
                    })
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
                resp_data = _resp_data(resp)
                if _resp_ok(resp) and resp_data:
                    audio_segment_ids.append(resp_data.get("audio_segment_id"))
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
                resp_data = _resp_data(resp)
                if _resp_ok(resp) and resp_data:
                    text_segment_ids.append(resp_data.get("text_segment_id"))
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
        ffmpeg = find_ffmpeg()
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

    # micro adjust shake keyframes
    if micro_cfg and video_segment_ids:
        shake_cfg = micro_cfg.get("shake") or {}
        try:
            interval = float(shake_cfg.get("interval", 0.2))
        except Exception:
            interval = 0.2
        try:
            max_keys = int(shake_cfg.get("max_keys", 12))
        except Exception:
            max_keys = 12
        try:
            intensity_x = float(shake_cfg.get("intensity_x", shake_cfg.get("intensity", 0)))
        except Exception:
            intensity_x = 0.0
        try:
            intensity_y = float(shake_cfg.get("intensity_y", shake_cfg.get("intensity", 0)))
        except Exception:
            intensity_y = 0.0
        if interval > 0 and max_keys > 0 and (intensity_x > 0 or intensity_y > 0):
            for idx, sid in enumerate(video_segment_ids):
                meta = video_segment_meta[idx] if idx < len(video_segment_meta) else {}
                if meta.get("apply_micro") is False:
                    continue
                duration = meta.get("duration") or 0
                if duration <= 0:
                    continue
                times = []
                t = 0.0
                while t < duration and len(times) < max_keys:
                    times.append(t)
                    t += interval
                if not times:
                    times = [0.0]
                for t in times:
                    t_str = f"{t:.3f}s"
                    if intensity_x > 0:
                        value = random.uniform(-intensity_x, intensity_x)
                        _record(svc.add_video_keyframe(draft_id, sid, "position_x", t_str, value, track_name=meta.get("track")),
                                f"micro_shake_x@{t_str}")
                        micro_applied = True
                    if intensity_y > 0:
                        value = random.uniform(-intensity_y, intensity_y)
                        _record(svc.add_video_keyframe(draft_id, sid, "position_y", t_str, value, track_name=meta.get("track")),
                                f"micro_shake_y@{t_str}")
                        micro_applied = True

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

    if micro_applied and "micro_adjust" not in summary["applied"]:
        summary["applied"].append("micro_adjust")

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


def generate_ai_task(task_id: str, user_id: int, key_id: int, task_type: str, payload: dict, save_text_file: bool = False):
    app = create_app()
    with app.app_context():
        from app.models.ai_task import AITask
        from app.models.user_api_key import UserApiKey
        from app.services.ai_service import generate_with_key

        task = AITask.query.get(task_id)
        if not task:
            return
        task.status = "started"
        db.session.add(task)
        db.session.commit()

        key = UserApiKey.query.filter_by(id=key_id, user_id=user_id).first()
        if not key:
            task.status = "failed"
            task.error_msg = "密钥不存在"
            db.session.add(task)
            db.session.commit()
            return

        result = generate_with_key(key, task_type, payload, save_text_file=save_text_file)
        if not result.get("ok"):
            task.status = "failed"
            task.error_msg = result.get("error") or "生成失败"
        else:
            task.status = "success"
            task.result_path = result.get("path")
            if task_type == "text":
                task.result_text = result.get("text") or ""
        db.session.add(task)
        db.session.commit()

