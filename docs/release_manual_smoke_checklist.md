# Release Manual Smoke Checklist

## Scope

This checklist covers the current release candidate before packaging a green build or installer.
It focuses on:

- official draft replacement
- selfbuilt draft replacement
- batch mix workflows
- manga assistant workflow
- AI account management and Duo UI
- settings and navigation behavior

## Environment

- Windows desktop runtime
- JianYing installed and able to open local drafts
- GG not required
- Use the packaged green build for final smoke, not only source mode

## Draft Replacement

### Official Draft

- Open an official draft template such as `4月3日 (1)` or `4月3日 (2)`.
- Replace only images and confirm the generated draft opens in JianYing.
- Replace video, image, audio, and text together and confirm:
  - draft opens
  - no missing media warning
  - text is changed
  - image, video, and audio are changed
- If batch count > 1, confirm the result area shows:
  - success count
  - failed count when applicable
  - selected materials for each generated draft

### Selfbuilt Draft

- Open `0314-01` or another selfbuilt placeholder draft.
- Replace images and text.
- Confirm:
  - generated draft opens
  - image replacement is visible
  - no 1970 timestamp issue
  - no broken draft metadata issue

## Batch Mix

### Group Mode

- Quick-create directories.
- Confirm one folder card per active slot.
- Remove one card using `X` and confirm the UI updates without deleting disk folders.
- Recreate directories and confirm the draft path binding is refreshed.

### Mix Mode

- Quick-create directories.
- Confirm only one `素材池` directory is created.
- Submit batch with `batch_count > 1`.
- If material pool is small, confirm a warning appears before task polling continues.
- After completion, confirm each generated draft row shows selected materials.

### Partition Mode

- Quick-create directories.
- Confirm directories are partition-oriented, not generic mixed slot folders.
- Submit generation and verify missing partitions fail early with clear messages.

### Sequence Mode

- Quick-create directories.
- Confirm one folder per slot.
- Use fewer videos than batch count and confirm warning mentions cyclic reuse.

## Manga Assistant

### Storyboard Workbench

- Open `漫剧助手 -> 分镜工作台`.
- Confirm the page shows four steps:
  - 文案转分镜
  - 确认镜头提示词
  - 按句生图
  - 回灌正式链路
- Generate storyboard SRT from a short text script.
- Confirm:
  - summary counts update
  - first storyboard prompt is auto-filled
  - storyboard cards render

### Image Generation

- Use `用于生图` from one storyboard card.
- Confirm prompt field updates.
- Generate one image.
- Confirm:
  - recent generated image preview appears
  - top summary state updates

### Next-Step Handoff

- From manga assistant, click `前往 AI 漫剧`.
- Confirm current storyboard content is carried into:
  - project name
  - manga script
- Click `前往批量混剪`.
- Confirm navigation succeeds and no stale draft selection is injected.

## AI Account Management

- Open `软件设置 -> AI账号管理`.
- Confirm providers are grouped by:
  - 生图模型
  - 脚本模型
  - 配音模型
- Confirm saved accounts are also grouped.
- Check spacing between groups and cards is visually readable.

## Duo UI

- Open `批量效果 -> Duo 资源`.
- Confirm the page reads as:
  - preset cards
  - quick settings
  - advanced settings
- Confirm spacing is readable and controls are not crowded.

## Settings And Navigation

- Open `软件设置 -> 工作台设置`.
- Confirm `自动恢复上次草稿` is no longer present.
- Switch between multiple functional panels and confirm draft selection does not silently bleed into another panel.
- For a panel with no selected draft, confirm the user is forced to choose a draft again.

## Result Rendering

- Run one successful batch task and confirm result area shows:
  - output draft count
  - generated draft names
  - selected materials per draft
  - warnings if pool reuse occurs
- Run one intentionally failing batch and confirm:
  - failed batch section appears
  - failure reason is visible
  - successful drafts remain listed

## Packaging Gate

Only package when all of the following are true:

- official draft replacement passes
- selfbuilt draft replacement passes
- batch mix result rendering is clear
- manga assistant handoff works
- no stale draft auto-restore behavior remains
- no blocker-level UI regression is visible
