# Windows Packaging

## Goal

Ship VideoFactory as an installer-first Windows desktop package:

- user chooses install drive during setup
- user launches directly after install
- user does not manually install Python
- user does not manually install Redis
- local client still depends on server-side member / VIP / quota / CDK / device verification

## Current Build Route

1. Prepare a production desktop preset from:
   - `env.presets/desktop_full.env.example`
2. Fill real values before release:
   - `SECRET_KEY`
   - `VIDEOFACTORY_KEY_ENCRYPTION_KEY`
   - `VF_OFFICIAL_SITE_URL=https://www.zysj.site`
   - optional `VF_DOWNLOAD_URL`
3. Keep desktop package in remote-auth mode:
   - `VF_REMOTE_AUTH_MODE=1`
   - `DEV_DATABASE_URL=sqlite:///data-runtime.sqlite`
   - do not ship MySQL `DATABASE_URL`
4. Run prepackage check:

```powershell
venv\Scripts\python.exe scripts\prepackage_check.py
```

If the release touches official draft generation, add template regression:

```powershell
venv\Scripts\python.exe scripts\prepackage_check.py `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日" `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日 (1)"
```

5. Build the desktop onedir bundle:

```powershell
venv\Scripts\python.exe scripts\build_desktop_bundle.py `
  --preset env.presets\desktop_full.env.example `
  --name VideoFactory `
  --icon C:\path\to\icon.ico `
  --logo C:\path\to\logo.png `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日" `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日 (1)"
```

6. Output:
   - bundle root: `build/release/VideoFactory`
   - installer template: `build/installer/VideoFactory_setup.iss`

## Notes

- `--icon` supports `.ico`; if you only provide `--logo` with `.png`, the build script will auto-generate an `.ico` for the exe.
- `--logo` can use `.png`; it will be copied into `branding/` for installer assets or later publishing.
- PyInstaller spec lives at `packaging/video_factory_desktop.spec`.
- Inno Setup template lives at `packaging/video_factory_installer.iss`.
- Final installer compilation is intentionally a separate step.

## What Gets Staged

- `.env` copied from the selected preset
- runtime directories:
  - `logs`
  - `user_data`
  - `runtime_tools`
  - `duo_cache`
  - `mcp_cache`
- `installer_manifest.json`
  - now includes git commit / branch / dirty state / build timestamp
  - now includes official draft service SHA256 and fix revision for build tracing

## Security Position

- desktop package only raises reverse-engineering cost
- real commercial protection still depends on the server
- sensitive local config and localhost runtime token cache are already encrypted before packaging
- installer should use remote-auth mode against `https://www.zysj.site`
- installer must not ship a MySQL connection string to end users
- installer must not ship a MySQL `root` account connection string

If the desktop package still needs direct database credentials to run, that means the current client/server boundary is not fully closed for release yet.

## Recommended Guardrails

- Follow [`docs/release_playbook.md`](/E:/JianYingApi/VideoFactory/docs/release_playbook.md)
- Treat official draft changes as high-risk and ship them separately
- Keep at least two fixed official draft templates as release blockers
