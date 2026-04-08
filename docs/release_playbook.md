# Release Playbook

这份文档用来约束后续更新方式，目标只有一个：
避免“顺手改几处”以后，把官方草稿、安装包和线上运行态一起带坏。

## 发布原则

1. `main` 只保留当前稳定版。
2. 新功能先在 `feature/*` 分支开发。
3. 准备发版时，从稳定分支切 `release/*`。
4. 高风险链路单独发版，不和 UI/文案/包装混发。
5. 不允许用“整仓回退到老 commit”代替修复，优先只回退模块文件或 `cherry-pick` 已验证修复。

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

发布目录里禁止出现这些内容：

- `.codex-tmp`
- `backups`
- `docs`
- `reverse_capture`
- `official_draft_regression`
- `tmp_*`
- `*.log`
- `*.tmp`
- `@AutomationLog.txt`
- `pyarmor.bug.log`

现在这条规则已经由：

- [`build_desktop_bundle.py`](/E:/JianYingApi/VideoFactory/scripts/build_desktop_bundle.py)
- [`prepackage_check.py`](/E:/JianYingApi/VideoFactory/scripts/prepackage_check.py)

直接拦截，不再靠人工记忆。
## 婧愮爜妗岄潰鐗堣仈璋冭鏄?

鍦?bug 淇闃舵锛屼紭鍏堢敤婧愮爜妗岄潰鐗堥獙璇侊紝涓嶇敤姣忔敼涓€娆″氨閲嶆柊鎵撳寘渚挎惡鍖咃細

```powershell
venv312\Scripts\python.exe desktop_app.py
```

杩欎釜鍏ュ彛浼氱洿鎺ヤ娇鐢ㄥ綋鍓嶅伐浣滃尯婧愮爜鍚姩妗岄潰澹筹紝閫傚悎楠岃瘉鑽夌璇诲彇銆佹枃浠?鐩綍閫夋嫨鍣ㄣ€佸揩閫熷垱寤虹洰褰曘€佹斁绱犳潗绛夋闈㈢壒鏈夐€昏緫銆?

濡傛灉婧愮爜妗岄潰鐗堝凡缁忛€氳繃杩欎竴杞祴璇曪紝鍙互鐩存帴鎵撳畨瑁呭寘锛屽啀鍋氬畨瑁呮€佺儫娴嬶紝涓嶅繀鍦ㄤ腑闂村啀閲嶅鎵撲竴娆＄豢鑹插厤瀹夎鍖呫€?

如果这次动到了官方草稿链路，必须带模板回归：

```powershell
venv312\Scripts\python.exe scripts\prepackage_check.py `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日" `
  --official-draft-template "E:\jycaogao\JianyingPro Drafts\4月3日 (1)"
```

这一步会调用 [`official_draft_regression.py`](/E:/JianYingApi/VideoFactory/scripts/official_draft_regression.py)，
直接生成探针草稿并检查 `draft_content.json / template.json / template.tmp` 的素材引用是否缺失。

如果想固定使用仓库里的金标准模板清单，不再手填路径，可以直接跑：

```powershell
venv312\Scripts\python.exe scripts\prepackage_check.py `
  --use-default-official-drafts
```

默认模板清单在：
[`official_draft_release_templates.json`](/E:/JianYingApi/VideoFactory/packaging/official_draft_release_templates.json)

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

### 3.0 发布清理规则

商用包只允许带：

- 运行所需二进制
- 模板与静态资源
- migrations
- env preset
- runtime tools
- branding
- installer manifest

不允许把开发资料、回归资料、逆向资料、临时文件和日志一起带出去。

### 3.1 第一批必须保护的本地模块

当前商用包第一批必须纳入保护的模块：

- [`app/views/api.py`](/E:/JianYingApi/VideoFactory/app/views/api.py)
- [`app/utils/auth_token.py`](/E:/JianYingApi/VideoFactory/app/utils/auth_token.py)
- [`app/services/jianying/official_draft_replace_service.py`](/E:/JianYingApi/VideoFactory/app/services/jianying/official_draft_replace_service.py)
- [`app/services/jianying/draft_replacement_strategy.py`](/E:/JianYingApi/VideoFactory/app/services/jianying/draft_replacement_strategy.py)
- [`app/tasks.py`](/E:/JianYingApi/VideoFactory/app/tasks.py)

这批先保护最值钱的本地链路，不全项目一起混淆，避免影响日常开发效率。

### 3.2 前端资源保护

当前发布脚本会在商用包阶段默认压缩：

- [`app/static/js/user-index.js`](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js)

这一步只作用于发布目录，不改工作区源码。

### 3.3 必须留在服务端的职责

以下能力不允许为了“本地更方便”再下放回桌面端：

- 授权激活 / 解绑
- 配额扣减 / 返还
- VIP 与功能开关
- 邀请奖励与会员时长结算
- 高价值账号与敏感配置校验

桌面端只保留执行壳、展示层和必要的本地运行逻辑，不承担最终裁决。

### 3.1 稳定版落点

每次人工验收通过后，必须再做两件事：

1. 给稳定提交打 tag，例如 `stable/v1.0.1`
2. 把该版本的安装包、便携包和 `installer_manifest.json` 一起归档

推荐命令：

```powershell
git tag -a stable/v1.0.1 -m "stable v1.0.1"
git show stable/v1.0.1 --no-patch --stat
```

以后修线上问题，优先：
- 从 `main` 或最近稳定 tag 新开 `hotfix/*`
- 只 `cherry-pick` 需要的修复
- 不整仓回退，不混入无关功能

### 4. 灰度顺序

固定顺序：

1. 本地源码验证
2. 便携包验证
3. 安装包验证
4. 线上同步

不要跳步骤，也不要“线上先替换看看”。

## 官方草稿专门规则

官方草稿是最高风险模块，单独遵守下面 5 条：

1. 没有模板回归，不允许发版。
2. 至少保留两份金标准模板：
   - `4月3日`
   - `4月3日 (1)`
3. 如果修的是官方草稿，不要同时修改 UI 和安装器逻辑。
4. 如果回归失败，优先回滚到上一个稳定服务文件，不现场叠补丁。
5. 金标准模板清单有变更时，必须和代码修改分开提交，避免“改了模板顺手放过 bug”。

## 紧急修复方式

如果线上或安装包已经出问题：

1. 先冻结当前版本
2. 新开 `hotfix/*`
3. 只修一个问题
4. 重新跑模板回归
5. 用新的 commit 重新出便携包和安装包

不要在原有发版分支上连续追加多个“顺手修复”。
也不要直接把仓库 reset 到老版本，再把新功能手搓补回去。

## 推荐命令

基础预检：

```powershell
venv312\Scripts\python.exe scripts\prepackage_check.py
```

使用仓库默认官方草稿模板集：

```powershell
venv312\Scripts\python.exe scripts\prepackage_check.py `
  --use-default-official-drafts
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

使用仓库默认官方草稿模板集打包：

```powershell
venv312\Scripts\python.exe scripts\build_desktop_bundle.py `
  --preset env.presets\desktop_zhiying_release.env `
  --name ZhiyingShijie `
  --exe-name 智映视界 `
  --use-default-official-drafts
```
