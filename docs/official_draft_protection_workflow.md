# Official Draft Protection Workflow

## Goal

Protect the lowest-level official draft logic without making everyday rule changes hard to maintain.

## Current Boundary

Keep these layers separate:

- Plain Python orchestration:
  - `app/services/jianying/official_draft_replace_service.py`
  - normal business rules, diagnostics, regression wiring
- Protected core modules:
  - `app/services/jianying/official_draft_codec.py`
  - `app/services/jianying/draft_replacement_strategy.py`

This keeps the replace service easy to edit while moving the harder-to-reproduce logic behind a smaller protected surface.

## Local Tooling

This repository already has a working PyArmor toolchain in the local virtualenv:

- `venv\\Scripts\\pyarmor.exe`
- `venv312\\Scripts\\pyarmor.exe`

The desktop build script now includes the official draft core modules in `PYARMOR_TARGETS`.

## Local Protection Smoke

Generate protected core modules with local PyArmor:

```powershell
venv\Scripts\python.exe scripts\protect_official_draft_core.py --clean
```

The helper tries a stronger PyArmor mode first. If the local trial license blocks it, it falls back to a minimal mode that still obfuscates the two core modules.

## Release Build

Build with obfuscation:

```powershell
venv\Scripts\python.exe scripts\build_desktop_bundle.py `
  --preset env.presets\desktop_full.env.example `
  --name VideoFactory `
  --icon C:\path\to\icon.ico `
  --logo C:\path\to\logo.png `
  --use-default-official-drafts `
  --obfuscate
```

## Why This Shape

- codec logic is the most sensitive part to expose
- strategy splitting is stable enough to protect
- service orchestration should stay easier to debug and patch

## Next Hardening Step

If PyArmor protection is no longer enough, replace the implementation behind:

- `official_draft_codec.load_official_draft_payload`
- `official_draft_codec.dump_official_draft_payload`
- `official_draft_codec.write_official_draft_payload`

with a native extension or external protected runtime, without changing the main replace flow.
