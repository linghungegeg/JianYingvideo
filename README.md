# JianYingvideo

剪映/CapCut 草稿自动化与桌面打包工具，支持新版剪映草稿结构，并接入 AI 生图模型。

VideoFactory is a Windows desktop packaging project for JianYing/CapCut draft automation workflows. This repository contains the public source code, packaging scripts, installer templates, migrations, documentation, and example environment presets needed to inspect or rebuild the desktop package.

## Public source boundary

The repository intentionally includes:

- `app/`, `blanks/`, `migrations/`, `packaging/`, `scripts/`, and `docs/`
- `env.presets/*.example` files
- desktop entrypoints such as `desktop_app.py`, `run.py`, and `run_worker.py`
- the embedded `app/utils/JianYingApi/` source dependency

The repository intentionally excludes local runtime and private release state:

- `.env`, real release presets, databases, logs, caches, and user uploads
- virtual environments, build output, packaged binaries, and installer output
- local runtime tools, third-party binary tool folders, and private server access notes

Packaged desktop binaries are published separately as GitHub Release assets instead of being committed to Git history.

## Packaging

The packaging flow is documented in `docs/windows_packaging.md` and uses:

```powershell
venv\Scripts\python.exe scripts\prepackage_check.py
venv\Scripts\python.exe scripts\build_desktop_bundle.py --preset env.presets\desktop_full.env.example --name ZhiyingShijie
```

For an actual public release build, use a private local preset with production values. Do not commit that preset.

## Release assets

Release downloads should be uploaded as GitHub Release assets, for example:

- `ZhiyingShijie_<version>.exe`
- optional portable zip packages
- `installer_manifest.json`

Always keep the release notes aligned with the manifest commit, branch, build time, and whether the working tree was clean when the package was produced.
