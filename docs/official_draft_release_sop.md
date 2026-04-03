# Official Draft Release SOP

## Goal

Ship a desktop build that:

- keeps official draft core logic protected
- does not require GG
- preserves the current official/selfbuilt draft replacement behavior

## Recommended Release Order

1. Run the normal prepackage checks.
2. Build the desktop workspace or release bundle.
3. Overlay the protected official draft core into that staged workspace.
4. Run official draft regression again against the staged output if the release touched draft logic.
5. Package the installer from the protected staged workspace.

## Minimal Commands

### A. Build the desktop bundle

```powershell
venv\Scripts\python.exe scripts\build_desktop_bundle.py `
  --preset env.presets\desktop_full.env.example `
  --name VideoFactory `
  --icon C:\path\to\icon.ico `
  --logo C:\path\to\logo.png `
  --use-default-official-drafts `
  --obfuscate
```

### B. Overlay the protected draft core

If the protected workspace is `build\obfuscated`:

```powershell
venv\Scripts\python.exe scripts\protect_official_draft_core.py `
  --clean `
  --overlay-into E:\JianYingApi\VideoFactory\build\obfuscated
```

If you need to overlay directly into another staged directory, point `--overlay-into` at that root instead.

### C. Re-run draft regression on the current source tree

```powershell
venv\Scripts\python.exe scripts\official_draft_regression.py `
  --template "E:\jycaogao\JianYingPro Drafts\4月3日 (2)" `
  --template "E:\jycaogao\JianYingPro Drafts\0314-01" `
  --keep-output
```

## Required Manual Checks

- install on a machine without GG
- official draft replacement still opens in 剪映
- selfbuilt draft replacement still opens in 剪映
- no `链接媒体丢失`
- replaced text / image / audio behave as expected

## Notes

- local PyArmor is currently a trial license, so the helper may fall back to minimal mode automatically
- this is acceptable for the current release phase because it still protects the narrow draft core boundary
- business orchestration remains editable in Python; only the core draft modules are protected

## Protected Modules

- `app/services/jianying/official_draft_codec.py`
- `app/services/jianying/draft_replacement_strategy.py`

## Related Docs

- [official_draft_protection_workflow.md](/E:/JianYingApi/VideoFactory/docs/official_draft_protection_workflow.md)
- [draft_regression_workflow.md](/E:/JianYingApi/VideoFactory/docs/draft_regression_workflow.md)
