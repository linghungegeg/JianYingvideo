# EXE Runtime Checklist

本清单面向桌面封包路径，默认产品运行在用户本机，并处理本地剪映 / CapCut 草稿。

## 推荐基线

- 使用 MySQL，不建议商业封包继续依赖 SQLite
- 主任务链路使用本地后台执行，不再依赖 `Redis + worker`
- `ffmpeg` / `ffprobe` 作为本地运行工具随 EXE 一起打包
- 可选模块通过环境开关控制，不靠删代码做区分

参考：

- [`env.presets/desktop_core.env.example`](/E:/JianYingApi/VideoFactory/env.presets/desktop_core.env.example)
- [`env.presets/desktop_full.env.example`](/E:/JianYingApi/VideoFactory/env.presets/desktop_full.env.example)
- [`docs/packaging_profiles.md`](/E:/JianYingApi/VideoFactory/docs/packaging_profiles.md)

## 运行时必须具备的逻辑组件

1. Web app 进程
   参考：[`run.py`](/E:/JianYingApi/VideoFactory/run.py)
2. MySQL 服务
   用于账号、授权、次数、配置等业务数据
3. 本地 FFmpeg 工具
   用于分割、素材导出、部分 AI / 漫剧导出链路

## 必做运行检查

封包前以及封包后都要确认：

1. MySQL 可连通，`DATABASE_URL` 指向 MySQL
2. `SECRET_KEY` 不是默认占位值
3. `VIDEOFACTORY_KEY_ENCRYPTION_KEY` 已配置
4. `logs`、`app/uploads`、`user_data` 目录可写
5. `ffmpeg` 可通过 `FFMPEG_PATH`、`PATH` 或 `runtime_tools/ffmpeg` 被发现
6. `/user` 工作台可以正常打开
7. 批量混剪、分割、微调、导出至少各跑一条核心链路

## 自检命令

```powershell
venv\Scripts\python.exe scripts\runtime_selfcheck.py
venv\Scripts\python.exe scripts\final_regression.py
```

可选 HTTP 探测：

```powershell
$env:VF_BASE_URL="http://127.0.0.1:5000"
venv\Scripts\python.exe scripts\runtime_selfcheck.py
```

脚本当前检查：

- 数据库后端与连通性
- 必需目录
- FFmpeg 可用性
- 生产环境密钥占位
- 功能开关状态
- 可选本地 HTTP 探测

## 推荐启动顺序

1. 启动 MySQL
2. 执行数据库迁移
3. 启动 Web app
4. 运行自检
5. 运行核心冒烟
6. 运行关键功能实测

## 验证命令

```powershell
venv\Scripts\python.exe -m flask db upgrade
venv\Scripts\python.exe run.py
venv\Scripts\python.exe scripts\runtime_selfcheck.py
venv\Scripts\python.exe scripts\final_regression.py
venv\Scripts\python.exe scripts\core_flow_smoke.py
```

## 封包说明

- EXE 应打包代码、静态资源与本地运行工具
- `ffmpeg` / `ffprobe` 建议直接落到 `runtime_tools/ffmpeg`
- 不再把 `Redis / worker` 作为商业版默认运行依赖
- 最终环境里仍应显式控制：
  - `LEGACY_TEMPLATE_ENDPOINTS_ENABLED`
  - `DUO_FEATURES_ENABLED`
  - `OPENCLAW_FEATURES_ENABLED`
  - `MANGA_FEATURES_ENABLED`

## 当前建议

当前商业封包策略建议围绕：

- 一个主 EXE 入口
- 一套本地运行工具目录
- 一份明确的环境文件
- 一轮封包前自检 + 核心流程实测
