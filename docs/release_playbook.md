# Release Playbook

这份文档用来约束后续更新方式，目标只有一个：
避免“顺手改几处”以后，把官方草稿、安装包和线上运行态一起带坏。

## 发布原则

1. `main` 只保留当前稳定版。
2. 新功能先在 `feature/*` 分支开发。
3. 准备发版时，从稳定分支切 `release/*`。
4. 高风险链路单独发版，不和 UI/文案/包装混发。

高风险链路包括：
- 官方草稿生成
- 剪映草稿打开 / root meta 注册
- 素材路径修复
- 导出链路

## 每次发版必须拆成三类

### 低风险

- 文案
- 静态页面
- 非核心设置项

这类可以和常规版本一起发。

### 中风险

- 漫剧助手
- 草稿扫描
- 任务中心
- 非官方草稿的普通工作流

这类先出便携包，再出安装包。

### 高风险

- 官方草稿替换服务
- 剪映兼容逻辑
- 安装包启动逻辑

这类一版只改一块，不允许夹带别的需求。

## 发版前固定流程

### 1. 自动检查

先跑基础检查：

```powershell
venv312\Scripts\python.exe scripts\prepackage_check.py
```

如果这次动到了官方草稿链路，必须带模板回归：

```powershell
venv312\Scripts\python.exe scripts\prepackage_check.py `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日" `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日 (1)"
```

这一步会调用 [`official_draft_regression.py`](/E:/JianYingApi/VideoFactory/scripts/official_draft_regression.py)，
直接生成探针草稿并检查 `draft_content.json / template.json / template.tmp` 的素材引用是否缺失。

### 2. 真机烟测

至少人工验证以下 5 项：

1. 扫草稿正常
2. 官方草稿生成正常
3. 剪映首页能识别新草稿
4. 双击或打开目录正常
5. 剪映里没有“链接媒体丢失”

### 3. 产物追溯

每次打包后，必须保存产物里的 [`installer_manifest.json`](/E:/JianYingApi/VideoFactory/build/release)。

现在 manifest 已经包含：
- `git_commit`
- `git_branch`
- `git_dirty`
- `built_at_utc`
- `official_draft_service_sha256`
- `official_draft_fix_revision`

这样以后安装包出问题时，可以直接对上“它到底是哪个提交、哪版官方草稿服务打出来的”。

### 4. 灰度顺序

固定顺序：

1. 本地源码验证
2. 便携包验证
3. 安装包验证
4. 线上同步

不要跳步骤，也不要“线上先替换看看”。

## 官方草稿专门规则

官方草稿是最高风险模块，单独遵守下面 4 条：

1. 没有模板回归，不允许发版。
2. 至少保留两份金标准模板：
   - `4月3日`
   - `4月3日 (1)`
3. 如果修的是官方草稿，不要同时修改 UI 和安装器逻辑。
4. 如果回归失败，优先回滚到上一个稳定服务文件，不现场叠补丁。

## 紧急修复方式

如果线上或安装包已经出问题：

1. 先冻结当前版本
2. 新开 `hotfix/*`
3. 只修一个问题
4. 重新跑模板回归
5. 用新的 commit 重新出便携包和安装包

不要在原有发版分支上连续追加多个“顺手修复”。

## 推荐命令

基础预检：

```powershell
venv312\Scripts\python.exe scripts\prepackage_check.py
```

官方草稿专项回归：

```powershell
venv312\Scripts\python.exe scripts\official_draft_regression.py `
  --template "E:\jycaogao\JianyingPro Drafts\4月3日" `
  --template "E:\jycaogao\JianyingPro Drafts\4月3日 (1)" `
  --keep-output `
  --report-json "build\official_draft_regression\report.json"
```

带官方草稿模板的打包：

```powershell
venv312\Scripts\python.exe scripts\build_desktop_bundle.py `
  --preset env.presets\desktop_zhiying_release.env `
  --name ZhiyingShijie `
  --exe-name 智映视界 `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日" `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日 (1)"
```
