# 功能映射清单

本文用于把原有“剪映助手能力清单”映射到当前 VideoFactory 的现状，方便后续判断哪些功能已经具备，哪些仍需补齐。

判定原则：

- 如果后端或 MCP 能力已经具备，即视为功能底层已具备。
- 前端是否已经完全接入，会单独标记。

## 一、批量替换类

| 一级分类 | 二级分类 | 核心能力 | 当前状态 | 现有入口 |
|---|---|---|---|---|
| 批量替换 | 素材替换 | 按组精确替换 | 已具备 | `frontend/index.html`、`/api/generate-batch`、`app/tasks.py` |
| 批量替换 | 素材替换 | 单层素材池顺序/随机替换 | 已具备 | `replace_mode=order/random` |
| 批量替换 | 素材替换 | 分区混剪替换 | 未完成 | 还缺按片段名或区域分组匹配逻辑 |

## 二、批量效果类

| 一级分类 | 二级分类 | 核心能力 | 当前状态 | 现有入口 |
|---|---|---|---|---|
| 批量效果 | 动画 | 批量添加入场/出场/组合动画 | 已具备 | `mcp_api.py`、`video.add_animation`、`text.add_animation` |
| 批量效果 | 视频效果 | 批量特效/滤镜/贴纸 | 已具备 | `video.add_effect`、`text.add_effect` |
| 批量效果 | 转场 | 自动添加转场 | 已具备 | `video.add_transition` |
| 批量效果 | 音频 | 音频片段、音量、时长、淡入淡出 | 已具备 | `audio.add_segment`、`audio.add_effect`、`audio.add_fade` |
| 批量效果 | 音频 | 音频关键帧 | 已具备 | `audio.add_keyframe` |
| 批量效果 | 字幕 | 文本替换与字幕效果 | 已具备 | 文本替换逻辑、`text.add_effect` |
| 批量效果 | 字幕 | SRT 字幕导入/匹配 | 未完成 | 还未看到完整解析和导入入口 |

## 三、批量分割类

| 一级分类 | 二级分类 | 核心能力 | 当前状态 | 现有入口 |
|---|---|---|---|---|
| 批量分割 | 分割 | 多文件批量分割 | 已具备基础能力 | `/api/split`、`app/utils/split_utils.py`、`app/templates/user/generate.html` |
| 批量分割 | 分割 | 单视频/单路径分割 | 已具备基础能力 | `/api/split`、`app/utils/split_utils.py`、`app/templates/user/generate.html` |
| 批量分割 | 裁剪 | 轨道时长裁剪 | 未完成 | 尚未形成完整前后端闭环 |

## 四、片段微调类

| 一级分类 | 核心能力 | 当前状态 | 现有入口 |
|---|---|---|---|
| 片段微调 | 随机变速 | 已具备 | `video.add_segment`、`audio.add_segment` 支持 `speed` |
| 片段微调 | 关键帧控制 | 已具备 | `video.add_keyframe` |
| 片段微调 | 缩放/位移/旋转 | 已具备 | `clip_settings`、`video.add_keyframe` |
| 片段微调 | 镜像翻转 | 已具备 | `clip_settings` 支持横向/纵向翻转 |

## 五、批量导出类

| 一级分类 | 核心能力 | 当前状态 | 现有入口 |
|---|---|---|---|
| 批量导出 | 草稿导出 | 已具备 | `draft.export` |

## 六、软件设置类

| 一级分类 | 核心能力 | 当前状态 | 现有入口 |
|---|---|---|---|
| 设置 | 草稿来源和路径设置 | 已具备 | 草稿路径配置、MCP 草稿读写能力 |
| 设置 | 素材路径设置 | 已具备 | `/api/material-folder` |
| 设置 | 用户偏好持久化 | 已具备 | `/api/drafts-folder`、`/api/material-folder` |
| 设置 | 导出目录设置 | 已具备 | `draft.export` 支持 `output_path` |
| 设置 | 授权/试用 | 已具备 | 登录、配额扣减、License/CDK 相关接口 |

## 当前缺失或未收口能力

- 分区混剪替换
- 轨道级时长裁剪闭环
- 分割能力的真实环境实测闭环

## MCP 相关能力参考

| 动作 | 说明 |
|---|---|
| `draft.create` | 创建草稿 |
| `draft.export` | 导出草稿 |
| `video.add_segment` | 添加视频片段 |
| `video.add_animation` | 添加视频动画 |
| `video.add_transition` | 添加转场 |
| `video.add_keyframe` | 添加视频关键帧 |
| `video.add_effect` | 添加视频特效 |
| `audio.add_segment` | 添加音频片段 |
| `audio.add_effect` | 添加音频特效 |
| `audio.add_fade` | 音频淡入淡出 |
| `audio.add_keyframe` | 音频关键帧 |
| `text.add_animation` | 文本动画 |
| `text.add_effect` | 文本效果 |
| `utility.find_effects` | 资源检索 |
