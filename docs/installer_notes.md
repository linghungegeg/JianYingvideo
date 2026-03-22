# Installer Notes

This project should ship to end users as an installer-first desktop package.

## Runtime Entry

- Use `run.py` as the installer runtime entrypoint.
- `run.py` now performs these steps before starting the local web service:
  - creates required runtime folders
  - runs Alembic `upgrade head`
  - starts the local web app
  - optionally opens the browser to `/user`

## Default Installer Env

- `VF_HOST=127.0.0.1`
- `VF_PORT=5000`
- `VF_DEBUG=0`
- `VF_AUTO_MIGRATE=1`
- `VF_OPEN_BROWSER=1`
- `VF_START_PATH=/user`
- `VF_REQUIRE_PRODUCTION_CONFIG=1` for installer builds
- `VF_REMOTE_AUTH_MODE=1`
- `VF_OFFICIAL_SITE_URL=https://www.zysj.site`
- `DEV_DATABASE_URL=sqlite:///data-runtime.sqlite`

Installer packaging should copy one preset into the runtime root as `.env` before release:

- `env.presets/desktop_core.env.example` for lean builds
- `env.presets/desktop_full.env.example` for full commercial builds

The packaged app should not rely on a developer-only `.env` outside the install directory.
The packaged app should not ship a MySQL connection string to end users.

## Delivery Target

The installer target is:

- user installs once
- user launches directly
- user does not manually install Python
- user does not manually install Redis
- user does not manually run `flask db upgrade`

## Safety Gate

If `VF_REQUIRE_PRODUCTION_CONFIG=1`, startup will block when:

- `VF_REMOTE_AUTH_MODE=0` and database is not MySQL
- `VF_REMOTE_AUTH_MODE=1` but `VF_OFFICIAL_SITE_URL` is missing
- `SECRET_KEY` is still the default placeholder
- BYOK encryption key is missing

## Packaging Reminder

- bundle Python runtime and project dependencies
- bundle static assets and templates
- bundle local runtime folders if needed
- keep `ffmpeg` / `ffprobe` discoverable from bundled runtime tools
- keep desktop runtime on local sqlite only for local task/runtime state
- keep server-side validation, VIP, quota, CDK, device binding, and referral logic enabled

## Site Settings

- public domain should stay on `https://www.zysj.site`
- download URL stays configurable in admin site settings
- logo URL stays configurable in admin site settings

These fields are maintained through `/api/site-settings` and should be set before release.

## Prepackage Command

Run this before the real installer build:

```powershell
venv\Scripts\python.exe scripts\prepackage_check.py
```

Optional fuller pass:

```powershell
venv\Scripts\python.exe scripts\prepackage_check.py --with-admin-browser-regression
```

## Desktop Bundle Command

Prepare the Windows onedir bundle and installer template:

```powershell
venv\Scripts\python.exe scripts\build_desktop_bundle.py `
  --preset env.presets\desktop_full.env.example `
  --name VideoFactory `
  --icon C:\path\to\icon.ico `
  --logo C:\path\to\logo.png
```

This command does not compile the final installer by itself. It prepares:

- `build/release/VideoFactory`
- `build/installer/VideoFactory_setup.iss`

If `--icon` is not provided but `--logo` points to a `.png`, the build script will auto-generate a Windows `.ico`.
