# GitHub Public Release Notes

## Source repository

Use this `VideoFactory` directory as the GitHub repository root. Do not publish the outer `E:\JianYingApi` workspace or detached worktrees such as `vf_wt_33a6904` and `vf_wt_804a5e5`.

The public repository should contain source, docs, example presets, packaging scripts, and installer templates. Runtime state and built artifacts must stay out of Git.

## Release artifact policy

Upload desktop packages through GitHub Releases:

- installer: `ZhiyingShijie_<version>.exe`
- optional portable package: `ZhiyingShijie_<version>_portable.zip`
- traceability file: `installer_manifest.json`

Do not commit `.exe`, `.zip`, `build/`, `dist/`, runtime caches, local databases, virtual environments, or real `.env` files to the source repository.

## Current local artifact found

Local installer:

```text
E:\JianYingApi\VideoFactory\build\installer\output\ZhiyingShijie_1.0.1.exe
```

Local manifest:

```text
E:\JianYingApi\VideoFactory\build\release\ZhiyingShijie\installer_manifest.json
```

Before attaching this artifact to a public release, confirm the manifest matches the intended release commit and that `git_dirty` is false. If it does not, rebuild the package from the clean public commit and upload the rebuilt artifact instead.
