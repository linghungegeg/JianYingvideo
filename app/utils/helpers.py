import random
import os
from flask import current_app
from app.extensions import db
from app.models.config import Config

def get_config(key, default=''):
    """获取配置值（从 config 表）"""
    config = Config.query.filter_by(key=key).first()
    return config.value if config else default

def set_config(key, value):
    """设置配置值"""
    config = Config.query.filter_by(key=key).first()
    if config:
        config.value = value
    else:
        config = Config(key=key, value=value)
        db.session.add(config)
    db.session.commit()

def get_material_folder():
    return get_config('material_folder')

def get_drafts_folder():
    return get_config('drafts_folder')

def set_drafts_folder(path):
    set_config('drafts_folder', path)

def pick_random_material():
    folder = get_material_folder()
    if not folder or not os.path.exists(folder):
        return None
    files = [f for f in os.listdir(folder) 
             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
    if not files:
        return None
    return os.path.join(folder, random.choice(files))

def log_generate(template_id, template_name, user_id, username, status, draft_name=None, error_msg=None):
    """记录生成日志（暂未实现）"""
    pass

def get_site_settings():
    return {
        'title': get_config('site_title', '视频工厂 - AI智能剪辑'),
        'keywords': get_config('site_keywords', '视频生成,AI剪辑,批量制作,剪映自动化'),
        'description': get_config('site_description', '视频工厂是专业的AI视频生成平台，支持批量制作、智能剪辑，让视频创作更简单。')
    }