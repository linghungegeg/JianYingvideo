# JianYingvideo

[中文](README.md) | [English](README_EN.md)

A Jianying / CapCut draft automation and Windows desktop packaging project, adapted for newer draft structures and connected with AI image generation workflows.

JianYingvideo is a Windows desktop application source project for short-video batch production, Jianying / CapCut draft automation, AI manga / image generation workflows, and membership-based commercial operation. It is not a single script. It combines local draft processing, a user workbench, an Admin console, license / CDK activation, quota management, AI account management, and a desktop packaging pipeline in one project.

The project is adapted for Jianying / CapCut 9+ draft structures. Actual compatibility depends on the local Jianying / CapCut version, draft structure, and asset paths. Before secondary development or commercial packaging, validate the workflow with your own real draft templates.

![JianYingvideo product and operation preview](app/static/images/landing/hero-dashboard.png)

## Quick Navigation

- [Screenshots](#screenshots)
- [Quick Start](#quick-start)
- [Desktop Modules](#desktop-modules)
- [Admin and Commercialization](#admin-and-commercialization)
- [Desktop Packaging](#desktop-packaging)
- [Server Deployment](#server-deployment)
- [Project Structure](#project-structure)
- [Contact and Donation](#contact-and-donation)

## Screenshots

The public repository only references tracked public images. It does not use images from `user_data/`, `app/uploads/`, `.videofactory-runtime/`, or local runtime caches.

| Product / Operation Page | Workbench / Batch Remix |
|---|---|
| ![Product and operation preview](app/static/images/landing/hero-dashboard.png) | ![Workbench and batch remix preview](app/static/images/landing/hero-workbench.png) |

| AI Manga / Image Generation | Effects / Assistant |
|---|---|
| ![AI manga and image generation](app/static/images/landing/feature-manga.png) | ![Batch effects](app/static/images/landing/feature-effects.png) |

![Assistant and configuration preview](app/static/images/landing/feature-assistant.png)

## What It Is For

- **Jianying / CapCut draft automation**: read, generate, replace, and export drafts to reduce repetitive manual editing.
- **Short-video matrix production**: batch workflows around reference drafts, material folders, text slots, and export queues.
- **AI manga and image-video production**: connect AI copywriting, image generation, storyboard assets, and draft generation.
- **Commercial Windows desktop software**: built-in login, VIP, quota, CDK, device binding, Admin console, and release packaging.
- **Private secondary development base**: keep MCP / API capabilities for custom models, asset services, automation tasks, or business logic.

## Core Strengths

- **Draft structure adaptation**: draft reading, writing, replacement, generation, and export around Jianying / CapCut structures.
- **Production and operation loop**: desktop handles local draft processing; server and Admin handle accounts, licenses, quota, announcements, agreements, and commercial settings.
- **Batch-first workflow**: group replacement, material-pool variation, partition folders, batch effects, splitting, tuning, and export are designed for batch production.
- **Pluggable AI capabilities**: AI account management, image generation, manga, copywriting, and TTS entry points are ready for extension.
- **Practical desktop packaging**: Windows EXE / installer scripts, Inno Setup template, prepackage checks, and manifest-based traceability.
- **Open source for development, practical for packaging**: source code is public, while real environment configs, runtime tools, and release artifacts stay outside Git history.

## What The Public Version Includes

The public repository includes source code, documentation, example presets, and packaging scripts for learning, review, and secondary development.

| Included | Not Included |
|---|---|
| Application source, user workbench, Admin, draft services, MCP/API, example configs, migrations, packaging scripts, installer templates | Real `.env`, real release presets, databases, logs, caches, uploaded user content, runtime tools, installers, portable packages |

Installers, portable packages, and `installer_manifest.json` should be distributed through GitHub Releases instead of being committed to Git history.

## Quick Start

### Local Development

These commands are for quickly starting a local development environment. For real commercial usage, use your own MySQL, `.env`, and server configuration.

```powershell
python -m venv venv
venv\Scripts\pip.exe install -r requirements.txt
venv\Scripts\python.exe -m flask db upgrade
venv\Scripts\python.exe run.py
```

After startup, verify the `/user` workbench first, then test batch remix, splitting, tuning, export, account center, and Admin features as needed.

### Desktop Packaging Entry

```powershell
venv\Scripts\python.exe scripts\prepackage_check.py
venv\Scripts\python.exe scripts\build_desktop_bundle.py --preset env.presets\desktop_full.env.example --name ZhiyingShijie
```

This is the public repository packaging entry point. For real releases, replace the example preset with your private release preset and never commit production secrets.

## Dependencies

### Local Development

- Windows 10/11.
- Python virtual environment, either the existing `venv` or a newly created one.
- MySQL for commercial or multi-user usage; SQLite is only suitable for temporary local debugging.
- FFmpeg / FFprobe for media splitting, audio/video processing, and export workflows.
- Jianying / CapCut 9+, with real draft folders and local material folders for compatibility regression.
- Local `.env` configuration. The public repository provides `.env.example`; real secrets, database settings, and production configs must not be committed.

### Desktop Packaging

- PyInstaller packaging is managed by `packaging/video_factory_desktop.spec` and `scripts/build_desktop_bundle.py`.
- Inno Setup is used for Windows installer generation, with the template in `packaging/video_factory_installer.iss`.
- Real release presets, runtime tools, FFmpeg, official draft regression templates, and private service configs are prepared locally and are not included in the public repository.
- Run `scripts/prepackage_check.py` before packaging. If official draft behavior is touched, add draft regression checks according to `docs/windows_packaging.md`.

### Server Deployment

- Linux server with Python 3.10+, MySQL, Nginx, and Gunicorn is recommended.
- The server handles login, registration, VIP, quota, CDK, device binding, invite rewards, resource review, and the Admin console.
- Server dependencies use `requirements.server.txt`; copy `env.presets/server_auth.env.example` to `.env` and fill real values.
- See `docs/server_auth_deploy.md` for details. Production servers should not run the user's local Jianying draft processing workflow.

## Desktop Modules

### Batch Remix

Batch remix is the main workflow. It generates multiple openable Jianying drafts from a reference draft.

- **Group replacement**: prepare matching folders for draft material slots.
- **Global variation**: all slots share one material pool and generate more combinations by order or random strategy.
- **Partition variation**: prepare structured folders such as intro, body, and outro for fixed-template production.
- **Text slots**: read draft text slots and batch import replacement text.
- **Result management**: list generated drafts and clean old results to reduce recognition conflicts.

### AI Video Creation

- Unified AI account management with service saving, enabling, testing, and model/channel settings.
- Extensible entry points for image-to-video, TTS, and AI copywriting.
- Recent materials, model accounts, and generation entries are placed in the workbench.

### AI Manga / Image Generation

- AI manga, storyboard, scene material folders, and draft generation workflow.
- Generated images and organized materials can continue into Jianying draft generation.
- Suitable for manga narration, short-drama storyboards, image-video content, and batch content factories.

### Batch Effects

- Animation, transitions, video effects, filters, stickers, and text effects.
- Duo resource entry and effect search entry are retained.
- Useful for adding unified effects or style processing after batch draft generation.

### Splitting, Fine Tuning, and Export

- File splitting, draft structure inspection, multi-draft queues, and main-video segment detection.
- Segment-level speed, offset, scale, rotation, mirror, keyframe, and local adjustment capabilities.
- Multi-draft export queue, export directory checks, and main-video segment export.

### Account Center, Settings, and Resource Exchange

- Account center shows membership status, remaining quota, usage, VIP expiration, check-in, invite, and activation.
- Settings manage workbench preferences, draft folders, material folders, export folders, and AI accounts.
- Resource exchange supports project name, description, contact info, membership level, review status, and publishing records.

## Admin and Commercialization

The project includes a backend foundation for commercial desktop software.

![Admin and operation preview](app/static/images/landing/hero-dashboard.png)

- **Users and roles**: registration, login, token validation, admin permission checks, user search, export, role management, and deletion.
- **Quota, VIP, and points**: remaining quota, total usage, VIP expiration, single-user and batch quota adjustment, check-in rewards, invite rewards, and quota logs.
- **License / CDK / device binding**: activation, online validation, deactivation, device fingerprint, device limits, transfer counts, and offline token strategy.
- **Site operation settings**: site name, logo, download URL, official URL, user agreement, privacy policy, announcements, contact channel, and card type display.
- **API commercialization**: API key management, permission templates, call quotas, audit logs, usage records, effect logs, and export capability.
- **Remote Auth mode**: the local Admin entry is disabled by default in desktop packages; users, licenses, CDKs, VIP, announcements, and operation configs should be managed by the server Admin console.

## Packaging Profiles and Feature Switches

The project keeps code in place and controls visible functionality through runtime switches.

| Profile | Scenario | Main Capabilities |
|---|---|---|
| Desktop Core | Local draft processing tool | Batch remix, splitting, tuning, export, account, license, local FFmpeg |
| Desktop Full | Commercial desktop package | Desktop Core + AI, Duo, OpenClaw, AI manga, commercial extension capabilities |

Common feature switches include `DUO_FEATURES_ENABLED`, `OPENCLAW_FEATURES_ENABLED`, `MANGA_FEATURES_ENABLED`, and `LEGACY_TEMPLATE_ENDPOINTS_ENABLED`. Commercial builds usually start from Desktop Full and disable only the features not needed by the business.

## Desktop Packaging

Packaging details are in `docs/windows_packaging.md`. Typical outputs include:

- Desktop bundle: `build/release/<name>/`
- Installer script: `build/installer/<name>_setup.iss`
- Build traceability: `installer_manifest.json`
- Optional installer binary generated by Inno Setup

Use a private release preset for real releases. The public repository keeps only `.example` presets.

## GitHub Releases

Desktop installers should be published through GitHub Releases, for example:

- `ZhiyingShijie_<version>.exe`
- Optional portable package: `ZhiyingShijie_<version>_portable.zip`
- `installer_manifest.json`

Release notes should match the commit, branch, build time, and `git_dirty` state recorded in the manifest.

## Server Deployment

Server deployment is for accounts, licenses, quotas, and backend operation in `remote-auth` mode. It does not process the user's local Jianying drafts.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.server.txt
cp env.presets/server_auth.env.example .env
gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app
```

The repository currently does not add a one-click deployment script. Use the commands above and refer to `docs/server_auth_deploy.md` and `docs/server_ops.md` for the deployment boundary.

## Project Structure

```text
app/                         Web backend, user workbench, Admin, API, draft services
app/models/                  User, task, license, CDK, quota, AI, and resource models
app/views/                   User, Admin, auth, MCP/API HTTP routes
app/services/                AI, quota, Jianying draft, batch generation, OpenClaw services
app/services/jianying/       Draft replacement, official draft compatibility, permission, usage, validation
app/static/                  Workbench, landing pages, images, CSS, JS, Swagger assets
app/templates/               Login, user workbench, Admin, landing, legacy templates
app/utils/                   Common utilities, encryption, paths, FFmpeg, license, runtime helpers
app/utils/JianYingApi/       Embedded third-party Jianying API source
app/utils/jianying_mcp/      Local MCP draft operation capability
blanks/                      Blank draft templates
docs/                        Packaging, release, settings, license, regression, feature docs
env.presets/                 Example environment presets; only .example files are public
migrations/                  Database migrations
packaging/                   PyInstaller / Inno Setup packaging configs
scripts/                     Checks, regression, packaging, release, diagnostics, helper scripts
config.py                    Flask / desktop runtime configuration
desktop_app.py               Windows desktop shell entry
run.py                       Web / local development entry
run_worker.py                Compatibility worker entry
runtime_paths_shared.py      Desktop runtime path helpers
wsgi.py                      WSGI entry
```

## Development Guide

- **User workbench**: start with `app/templates/user/index.html`, `app/static/js/user-index.js`, `app/static/css/user-index.css`, and `app/views/api.py`.
- **Admin / commercialization**: start with `app/views/admin.py`, `app/templates/user/admin.html`, and user/license/CDK/quota models.
- **Jianying draft capability**: start with `app/services/jianying/`, `app/utils/jianying_mcp/`, and `app/utils/JianYingApi/`.
- **AI capability**: start with `app/services/ai_service.py`, `app/services/openclaw_client.py`, `app/models/ai_provider.py`, and `app/models/user_api_key.py`.
- **Packaging and release**: start with `scripts/build_desktop_bundle.py`, `scripts/prepackage_check.py`, `packaging/`, and `docs/windows_packaging.md`.
- **Commercial packaging**: choose Desktop Core or Desktop Full first, then expose AI, Duo, OpenClaw, and AI manga through runtime switches.

## Current Boundaries

- Partition variation has entries and folder guidance, but real business templates still need validation against actual draft structures.
- File splitting and draft structure inspection have basic capabilities; production environments should still run regression tests by material type.
- AI, Duo, OpenClaw, and AI manga depend on runtime switches, account configuration, and external service availability.
- This project is not an official Jianying / CapCut project. Jianying / CapCut and related trademarks belong to their respective owners. Users must verify local app versions, draft folders, and material paths.

## Contact and Donation

If this project helps you, donations are welcome to support maintenance. For commercial cooperation, custom development, deployment, packaging, Jianying draft adaptation, or secondary development questions, contact the author through WeChat.

| WeChat Contact | Donation |
|---|---|
| ![WeChat contact](wx.jpg) | ![Donation code](zhanshang.png) |

## Credits

This project references and reuses ideas or code from several open-source projects around Jianying / CapCut draft automation:

- [JianYing-Automation/JianYingApi](https://github.com/JianYing-Automation/JianYingApi): third-party Jianying API project. The embedded `app/utils/JianYingApi/` source comes from this project and keeps its MIT License.
- [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft): Python draft generation and editing toolkit. This project references that ecosystem for MCP draft export, effect enums, and related draft capabilities.

Thanks to the authors and the community for exploring Jianying / CapCut automation.

## License

This project uses the MIT License. You may use, copy, modify, distribute, and commercially use the code, but you must keep the original copyright notice and license text.
