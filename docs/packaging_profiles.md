# Packaging Profiles

当前项目采用“保留代码，通过运行时开关控制功能暴露”的封包策略。

## 推荐封包档位

### Desktop Core

参考：
[`env.presets/desktop_core.env.example`](/E:/JianYingApi/VideoFactory/env.presets/desktop_core.env.example)

适用场景：

- 以本地剪映草稿处理为核心
- 优先保留批量混剪、分割、微调、导出、账户、授权
- 可选模块默认关闭

默认状态：

- `LEGACY_TEMPLATE_ENDPOINTS_ENABLED=0`
- `DUO_FEATURES_ENABLED=0`
- `OPENCLAW_FEATURES_ENABLED=0`
- `MANGA_FEATURES_ENABLED=0`

### Desktop Full

参考：
[`env.presets/desktop_full.env.example`](/E:/JianYingApi/VideoFactory/env.presets/desktop_full.env.example)

适用场景：

- 商业完整版封包
- 需要保留 AI、Duo、OpenClaw、AI 漫剧等能力

默认状态：

- `LEGACY_TEMPLATE_ENDPOINTS_ENABLED=1`
- `DUO_FEATURES_ENABLED=1`
- `OPENCLAW_FEATURES_ENABLED=1`
- `MANGA_FEATURES_ENABLED=1`

## 当前封包原则

- 保留所有主功能代码
- 用环境开关控制功能是否显示
- 主任务链路不再依赖 `Redis + worker`
- 本地执行功能尽量直接随 EXE 打包
- `ffmpeg` / `ffprobe` 建议直接进 `runtime_tools/ffmpeg`

## 推荐验证

封包前运行：

- [`docs/exe_runtime_checklist.md`](/E:/JianYingApi/VideoFactory/docs/exe_runtime_checklist.md)
- [`docs/final_manual_regression.md`](/E:/JianYingApi/VideoFactory/docs/final_manual_regression.md)
- `venv\Scripts\python.exe scripts\runtime_selfcheck.py`
- `venv\Scripts\python.exe scripts\final_regression.py`
- `venv\Scripts\python.exe scripts\core_flow_smoke.py`

## 当前建议

商业版优先从 `Desktop Full` 出发，再按业务需要关闭少数功能；不要再回到“主链路依赖 Redis / worker”的旧架构。
