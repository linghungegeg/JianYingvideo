# 软件设置与配置项盘点

本文档用于阶段 2：统一设置体系。

目标：
- 找出当前所有配置项
- 标记配置当前存在哪里
- 标记哪些配置重复、哪些入口过时、哪些应迁移到统一设置中心

## 一、当前配置存储来源

当前项目存在 4 套配置来源：

1. 浏览器本地 `localStorage`
- 读写入口： [user-index.js](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js)
- 关键函数：`getWorkspaceSettings()`、`setWorkspaceSettings()`
- 特点：只保存在当前机器当前浏览器环境，对 EXE 封包一致性不友好

2. 通用站点配置表
- 接口： [api.py](/E:/JianYingApi/VideoFactory/app/views/api.py) 中 `/api/material-folder`、`/api/drafts-folder`、`/api/settings`
- 特点：偏旧方案，仍被旧设置页使用

3. 用户级配置
- 接口： [api.py](/E:/JianYingApi/VideoFactory/app/views/api.py) 中 `/api/user/config`
- 当前主要用途：保存 `openclaw`
- 特点：更适合未来统一用户级设置

4. 页面执行参数
- 分散在各业务模块输入框
- 特点：不是全局设置，但目前和全局配置有混用

## 二、当前已识别配置项

### A. 工作台本地设置

来源：
- [user-index.js](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js)

当前字段：
- `strategy`
- `auto_discover`
- `auto_load_last_draft`
- `last_draft_version`
- `last_draft_path`
- `last_materials_root`
- `last_audio_root`
- `net_provider`
- `net_base_url`
- `net_token`

问题：
- 与“真正的全局设置”混在一起
- 封包后如果用户切换环境，配置不可迁移
- `net_*` 已经属于服务设置，不应继续只放本地存储

建议归属：
- `strategy / auto_discover / auto_load_last_draft` -> 工作台设置
- `last_*` -> 会话/最近使用记录，保留本地
- `net_*` -> 服务设置，迁移到统一配置

### B. 路径配置

来源：
- 旧设置页 [settings_page.html](/E:/JianYingApi/VideoFactory/app/templates/user/settings_page.html)
- 后端接口 [api.py](/E:/JianYingApi/VideoFactory/app/views/api.py)：
  - `/api/material-folder`
  - `/api/drafts-folder`

当前字段：
- `material_folder`
- `drafts_folder`

问题：
- 旧设置页仍然可用，和工作台设置并行
- 工作台新设置没有完整接管这些路径配置

建议归属：
- 统一迁移到 `软件设置 -> 路径与目录`

### C. 采集服务配置

来源：
- 工作台 `软件设置 -> 采集服务`
- 读取逻辑： [user-index.js](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js) `initSettingsWorkspace()`、`startNetAssets()`

当前字段：
- `net_provider`
- `net_base_url`
- `net_token`

当前存储：
- 仅 `localStorage`

问题：
- 属于“服务级配置”，不应只保存在前端本地
- 与封包后的稳定性目标不一致

建议归属：
- 迁移到 `用户级配置` 或统一设置接口

### D. AI 漫剧服务配置

来源：
- AI 漫剧页面中的 `OpenClaw` 弹窗
- 接口： [api.py](/E:/JianYingApi/VideoFactory/app/views/api.py) `/api/user/config`

当前字段：
- `openclaw.base_url`
- `openclaw.token`

问题：
- 配置入口在业务页中
- 配置职责和业务执行混在一起
- 对用户暴露了技术名词 `OpenClaw`

建议归属：
- 迁移到 `软件设置 -> 服务设置 -> AI 漫剧服务`

### E. AI 账号配置

来源：
- 工作台 `软件设置 -> AI 账号管理`
- 接口：
  - `/api/ai/providers`
  - `/api/user/keys`
  - `/api/user/keys/<id>`
  - `/api/user/keys/<id>/test`

当前字段：
- `provider_code`
- `key_name`
- `api_key`
- `api_secret`
- `endpoint`
- `base_url`
- `is_active`

问题：
- provider 可用性依赖数据库预置
- 前端可用性提示不够完善

建议归属：
- 继续保留在 `软件设置 -> AI 账号管理`
- 增加 provider 初始化与空状态兜底

### F. 导出执行参数

来源：
- 工作台 `批量导出`

当前字段：
- `export_dir`
- `export_pattern`
- `export_format`
- `export_resolution`
- `export_fps`
- `export_enable`
- `export_cover`
- `export_log`

问题：
- 部分字段是当前任务参数，部分字段有成为默认偏好的潜力

建议归属：
- 当前任务参数继续留在业务页
- 如果要做“默认导出目录”，应新增到 `路径与目录`

## 三、当前重复与冲突

### 1. 设置入口重复

重复入口：
- 工作台 `软件设置`
- 旧 [settings_page.html](/E:/JianYingApi/VideoFactory/app/templates/user/settings_page.html)
- AI 漫剧中的 `OpenClaw` 弹窗

处理建议：
- 统一只保留工作台 `软件设置`
- 旧设置页退出主流程
- AI 漫剧弹窗并入统一设置

### 2. 配置存储分裂

当前并行：
- `localStorage`
- 配置表
- 用户配置表

处理建议：
- 全局配置：统一落后端
- 最近使用记录：保留前端本地
- 当前任务参数：保留业务页，不做全局保存

### 3. 技术配置暴露在业务页

典型例子：
- `OpenClaw`

处理建议：
- 配置层内收
- 业务页只保留“可用/不可用/去设置”的结果，不暴露技术名词

## 四、统一后的建议结构

### 软件设置

1. 工作台设置
- 默认处理策略
- 自动发现草稿
- 自动恢复上次草稿

2. 路径与目录
- 草稿目录
- 默认素材目录
- 默认导出目录

3. 服务设置
- 采集服务
- AI 漫剧服务

4. AI 账号管理
- OpenAI
- 即梦
- 火山 TTS
- 其他兼容提供方

## 五、阶段 2 实施顺序

1. 确认哪些字段必须落后端
2. 设计统一设置读取/保存接口
3. 将 `采集服务` 从本地设置迁移到统一配置
4. 将 `OpenClaw` 从 AI 漫剧页面迁移到统一配置
5. 将旧设置页涉及的目录配置迁移到工作台设置
6. 清理旧入口与重复保存逻辑

## 六、当前阶段结论

当前最需要修复的不是单个页面，而是“配置体系分裂”。

如果不先做这个收口：
- EXE 封包后不同环境行为会不一致
- 用户无法判断去哪里改配置
- AI、采集、路径相关问题会持续反复
