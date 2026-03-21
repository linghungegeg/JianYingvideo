from app import create_app
from app.utils.desktop_runtime import (
    desktop_server_options,
    desktop_target_url,
    ensure_runtime_dirs,
    open_browser_later,
    run_startup_migrations,
    validate_installer_config,
)


app = create_app()


if __name__ == '__main__':
    ensure_runtime_dirs(app)
    validate_installer_config(app)
    run_startup_migrations(app)
    server_options = desktop_server_options()
    open_browser_later(desktop_target_url(server_options))
    app.run(**server_options)
