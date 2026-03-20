# EXE Packaging Inventory

本文件用于区分：哪些内容应保留在桌面版 EXE 中，哪些更适合做成可选模块或服务端能力。

## 应保留在 EXE 中

这些内容直接服务本地工作台、本地草稿处理和本地执行链路，应保留：

- [`app/views/user.py`](/E:/JianYingApi/VideoFactory/app/views/user.py)
  用户入口与工作台页面

- [`app/templates/user/index.html`](/E:/JianYingApi/VideoFactory/app/templates/user/index.html)
  当前唯一用户工作台入口

- [`app/static/js/user-index.js`](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js)
  工作台前端逻辑

- [`app/static/css/user-index.css`](/E:/JianYingApi/VideoFactory/app/static/css/user-index.css)
  工作台样式

- [`app/views/api.py`](/E:/JianYingApi/VideoFactory/app/views/api.py)
  用户工作台所需 API、账户、授权、草稿、本地工具链能力

- [`app/tasks.py`](/E:/JianYingApi/VideoFactory/app/tasks.py)
  本地后台任务执行

- [`app/services/jianying_service.py`](/E:/JianYingApi/VideoFactory/app/services/jianying_service.py)
  草稿操作与 MCP 封装

- [`app/utils/jianying_mcp`](/E:/JianYingApi/VideoFactory/app/utils/jianying_mcp)
  本地草稿操作运行时

- [`app/utils/JianYingApi`](/E:/JianYingApi/VideoFactory/app/utils/JianYingApi)
  草稿解析与本地草稿辅助

- [`app/utils/helpers.py`](/E:/JianYingApi/VideoFactory/app/utils/helpers.py)
  草稿目录、素材目录、日志与用户配置

- [`app/utils/ffmpeg_utils.py`](/E:/JianYingApi/VideoFactory/app/utils/ffmpeg_utils.py)
  FFmpeg 发现逻辑

- [`runtime_tools/ffmpeg`](/E:/JianYingApi/VideoFactory/runtime_tools/ffmpeg)
  本地 `ffmpeg` / `ffprobe`

## 可按商业策略选择保留

- [`app/views/admin.py`](/E:/JianYingApi/VideoFactory/app/views/admin.py)
  管理后台

- [`app/templates/user/admin.html`](/E:/JianYingApi/VideoFactory/app/templates/user/admin.html)
  管理后台 UI

- 授权 / CDK / License 相关接口
  如果 EXE 仍然需要激活授权，应保留

- [`app/views/mcp_api.py`](/E:/JianYingApi/VideoFactory/app/views/mcp_api.py)
  只有在保留本地自动化 API 面时才需要

## 更适合按开关控制

- Duo 资源能力
- OpenClaw 能力
- AI 漫剧能力
- 旧模板兼容接口

这些能力建议：

- 代码保留
- 通过环境变量控制入口显示
- 商业版按具体档位开启

## 当前不再建议作为主链路依赖

- `Redis`
- `worker`
- 以 `RQ` 为核心的任务执行路径

这些内容可以保留在仓库里做兼容或历史参考，但不再是桌面商业版主链路。

## 推荐封包模式

### Desktop Core

- 用户工作台
- 本地草稿处理
- 本地分割 / 微调 / 导出
- 账户 / 授权
- 本地 FFmpeg

### Desktop Full

- Desktop Core 全部内容
- AI 能力
- Duo 资源
- OpenClaw / AI 漫剧
- 授权与管理扩展能力
