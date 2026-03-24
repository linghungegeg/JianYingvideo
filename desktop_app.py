import ctypes
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def _init_logging() -> str:
    from app.utils.runtime_paths import runtime_path

    log_dir = runtime_path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "desktop-launch.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )
    return str(log_file)


def _message_box(title: str, message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        pass


def _wait_until_ready(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= int(response.status) < 500:
                    return
        except (urllib.error.URLError, socket.error, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"desktop server not ready: {last_error}")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _ensure_fixed_runtime_base_dir() -> str:
    existing = str(os.getenv("VF_RUNTIME_BASE_DIR") or "").strip()
    if existing:
        return existing

    candidates = [
        os.getenv("LOCALAPPDATA"),
        os.getenv("APPDATA"),
        os.getenv("TEMP"),
        os.getenv("TMP"),
    ]
    base_root = ""
    for item in candidates:
        value = str(item or "").strip()
        if value:
            base_root = value
            break
    if not base_root:
        base_root = str(Path.home())

    runtime_base = str(Path(base_root).expanduser().resolve() / "VideoFactoryDesktop")
    os.environ["VF_RUNTIME_BASE_DIR"] = runtime_base
    return runtime_base

def main() -> int:
    _ensure_fixed_runtime_base_dir()
    from werkzeug.serving import make_server
    from app import create_app
    from app.utils.desktop_runtime import (
        desktop_server_options,
        desktop_target_url,
        ensure_runtime_dirs,
        run_startup_migrations,
        validate_installer_config,
    )
    from app.utils.desktop_dialogs import set_active_window
    from app.utils.runtime_paths import runtime_path

    class ServerThread(threading.Thread):
        def __init__(self, app, host: str, port: int):
            super().__init__(daemon=True)
            self._server = make_server(host, port, app, threaded=True)
            self.port = int(self._server.server_port)

        def run(self) -> None:
            self._server.serve_forever()

        def stop(self) -> None:
            try:
                self._server.shutdown()
            except Exception:
                logging.exception("shutdown desktop server failed")

    log_file = _init_logging()
    server_thread = None
    try:
        runtime_base = str(os.getenv("VF_RUNTIME_BASE_DIR") or "").strip()
        logging.info("desktop runtime base dir: %s", runtime_base)
        app = create_app()
        ensure_runtime_dirs(app)
        validate_installer_config(app)
        run_startup_migrations(app)

        server_options = desktop_server_options()
        server_thread = ServerThread(app, server_options["host"], server_options["port"])
        server_thread.start()

        target_url = desktop_target_url({**server_options, "port": server_thread.port})
        _wait_until_ready(f"http://{server_options['host']}:{server_thread.port}/api/runtime-features")

        import webview

        window = webview.create_window(
            os.getenv("VF_DESKTOP_WINDOW_TITLE", app.config.get("SITE_NAME", "智映视界")),
            target_url,
            width=int(os.getenv("VF_DESKTOP_WIDTH", "1440")),
            height=int(os.getenv("VF_DESKTOP_HEIGHT", "960")),
            min_size=(1120, 760),
            text_select=True,
        )
        set_active_window(window)
        logging.info("desktop window ready: %s", target_url)
        if _env_flag("VF_DESKTOP_TEST_MODE", False):
            close_after = max(float(os.getenv("VF_DESKTOP_TEST_SECONDS", "5")), 1.0)

            def _close_window() -> None:
                time.sleep(close_after)
                try:
                    window.destroy()
                except Exception:
                    logging.exception("auto close desktop test window failed")

            threading.Thread(target=_close_window, daemon=True).start()
        webview.start(
            debug=False,
            private_mode=False,
            storage_path=str(runtime_path("webview")),
        )
        logging.info("desktop window closed")
        return 0
    except Exception as exc:
        logging.exception("desktop launch failed")
        _message_box("智映视界启动失败", f"{exc}\n\n日志位置：{log_file}")
        return 1
    finally:
        if server_thread is not None:
            server_thread.stop()


if __name__ == "__main__":
    raise SystemExit(main())
