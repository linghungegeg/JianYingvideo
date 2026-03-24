# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


PROJECT_ROOT = Path(os.getenv("VF_PROJECT_ROOT") or os.getcwd()).resolve()
BUILD_CONSOLE = os.getenv("VF_BUILD_CONSOLE", "0") == "1"
ICON_PATH = os.getenv("VF_EXE_ICON", "").strip()
APP_NAME = os.getenv("VF_BUILD_APP_NAME", "VideoFactory")
EXE_NAME = os.getenv("VF_BUILD_EXE_NAME", APP_NAME)
ENABLE_UPX = os.getenv("VF_ENABLE_UPX", "0") == "1"

datas = [
    (str(PROJECT_ROOT / "app" / "templates"), "app/templates"),
    (str(PROJECT_ROOT / "app" / "static"), "app/static"),
    (str(PROJECT_ROOT / "app" / "utils" / "duo_resources"), "app/utils/duo_resources"),
    (str(PROJECT_ROOT / "migrations"), "migrations"),
    (str(PROJECT_ROOT / "env.presets"), "env.presets"),
    (str(PROJECT_ROOT / ".env.example"), "."),
]

runtime_tools_dir = PROJECT_ROOT / "runtime_tools"
if runtime_tools_dir.exists():
    datas.append((str(runtime_tools_dir), "runtime_tools"))

datas += collect_data_files("webview")
binaries = collect_dynamic_libs("webview")

hiddenimports = []
for package_name in (
    "app.views",
    "app.models",
    "app.services",
    "app.utils",
):
    hiddenimports.extend(collect_submodules(package_name))

hiddenimports.extend([
    "logging.config",
    "logging.handlers",
    "pymysql",
    "cryptography.fernet",
    "redis",
    "rq",
    "webview",
])
hiddenimports.extend(collect_submodules("webview"))


a = Analysis(
    [str(PROJECT_ROOT / "desktop_app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=ENABLE_UPX,
    console=BUILD_CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=ICON_PATH if ICON_PATH.lower().endswith(".ico") and Path(ICON_PATH).exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=ENABLE_UPX,
    upx_exclude=[],
    name=APP_NAME,
)
