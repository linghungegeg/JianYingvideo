# VideoFactory EXE 封包阶段推进方案

本文档用于把当前工作台整理为“可一次性修复、可集中测试、可封包”的推进方案。

原则：
- 不排除现有功能，全部纳入 EXE 封包范围
- 不再边改边修，按阶段推进
- 每阶段结束先做自检，再进入下一阶段
- 最终以“我自检通过 + 你集中测试通过 + 再封包”为目标

## 一、当前总体判断

当前工程已经从“功能开发期”进入“迁移后收口期”。

主要系统性问题有 5 类：

1. 导航机制刚完成统一，但模块职责还未完全统一
2. 全局配置分散在多个入口，存在重复设置和历史入口
3. AI 类功能依赖较多，运行状态、配置状态、实际可用性之间不够一致
4. 部分功能仍带有迁移残留痕迹，尤其是 `AI 漫剧 / OpenClaw / 旧设置页`
5. 目前缺少一份以“封包”为目标的统一验收口径

## 二、封包范围

本次 EXE 封包按“全功能封包”处理，覆盖：

- 批量混剪
- 素材获得
- AI 成片
- AI 漫剧
- 批量效果
- 批量分割
- 片段微调
- 批量导出
- 软件设置
- 账户中心
- Duo 能力
- OpenClaw 依赖链路
- 管理后台必要能力
- 运行开关与打包配置

## 三、当前关键代码事实

### 1. 运行开关

配置文件 [config.py](/E:/JianYingApi/VideoFactory/config.py) 当前默认：

- `DUO_FEATURES_ENABLED=1`
- `OPENCLAW_FEATURES_ENABLED=1`
- `MANGA_FEATURES_ENABLED=1`

但文档 [optional_feature_switches.md](/E:/JianYingApi/VideoFactory/docs/optional_feature_switches.md) 仍按“桌面精简版默认关闭”编写。

这说明：
- 当前代码默认是“全能力构建”
- 文档和封包目标需要重新统一

### 2. 工作台入口

主工作台页面在 [index.html](/E:/JianYingApi/VideoFactory/app/templates/user/index.html)。

统一导航状态逻辑位于 [user-index.js](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js) 中的：

- `WORKSPACE_NAV_CONFIG`
- `applyWorkspaceNavigation()`
- `loadRuntimeFeatures()`
- `applyRuntimeFeatureVisibility()`

### 3. AI 漫剧不是纯前端残留

AI 漫剧已具备完整前后端链路：

- 前端页面与交互： [index.html](/E:/JianYingApi/VideoFactory/app/templates/user/index.html)
- 前端逻辑： [user-index.js](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js)
- 后端接口： [api.py](/E:/JianYingApi/VideoFactory/app/views/api.py)
- 外部服务客户端： [openclaw_client.py](/E:/JianYingApi/VideoFactory/app/services/openclaw_client.py)
- 模板与历史表： [manga_template.py](/E:/JianYingApi/VideoFactory/app/models/manga_template.py)、[manga_generation_log.py](/E:/JianYingApi/VideoFactory/app/models/manga_generation_log.py)

当前问题不在于“没有代码”，而在于：
- 对外暴露的是技术接入态，不是产品完成态
- 强依赖 `OpenClaw`
- 对未配置、不可达、关闭开关等状态的产品化处理还不够统一

### 4. AI 账号管理存在可用性风险

相关接口在 [api.py](/E:/JianYingApi/VideoFactory/app/views/api.py)：

- `/api/ai/providers`
- `/api/user/keys`
- `/api/user/keys/<id>`
- `/api/user/keys/<id>/test`

相关前端逻辑在 [user-index.js](/E:/JianYingApi/VideoFactory/app/static/js/user-index.js)：

- `loadAiProviders()`
- `loadAiKeys()`
- `saveAiKey()`
- `testAiKey()`

潜在风险：
- provider 数据来自数据库和迁移
- 若 provider 初始化异常，前端会表现为“不可用”

### 5. 设置体系存在重复入口

当前配置入口至少包括：

- 工作台中的 `软件设置`
- AI 漫剧内 `OpenClaw` 配置弹窗
- 旧设置页 [settings_page.html](/E:/JianYingApi/VideoFactory/app/templates/user/settings_page.html)

这会导致：
- 用户不知道同类配置应该去哪里改
- 业务页与设置页职责混在一起

## 四、功能依赖总表

### A. 核心工作流功能

| 功能 | 前端入口 | 关键 API | 关键依赖 | 当前风险 |
|---|---|---|---|---|
| 批量混剪 | `/user` 工作台 | `/api/generate-batch` `/api/task/<id>` | 草稿发现、素材目录、任务轮询 | 中 |
| 批量效果 | 工作台 `批量效果` | `/api/effects/*` `/api/apply-effect` | 效果资源、可选 Duo、FFmpeg | 中 |
| 批量分割 | 工作台 `批量分割` | `/api/split` `/api/draft/split-main-track` | FFmpeg、草稿结构 | 中 |
| 片段微调 | 工作台 `片段微调` | `/api/micro-adjust` | 草稿读取、导出参数 | 中 |
| 批量导出 | 工作台 `批量导出` | `/api/export/drafts` `/api/export/main-track` | 草稿路径、导出目录 | 中 |
| 素材获得 | 工作台 `素材获得` | `/api/net-assets/start` | 采集服务配置、目录选择 | 中 |

### B. AI 相关功能

| 功能 | 前端入口 | 关键 API | 关键依赖 | 当前风险 |
|---|---|---|---|---|
| AI 账号管理 | 软件设置 | `/api/ai/providers` `/api/user/keys` | Provider 数据、用户密钥表 | 高 |
| AI 成片 | 工作台 `AI 成片` | `/api/ai/generate/*` `/api/ai/task/<id>` | 已保存账号、外部 AI 服务 | 高 |
| AI 漫剧 | 工作台 `AI 漫剧` | `/api/ai/manga/generate` `/api/manga/*` `/api/openclaw/*` | OpenClaw 服务、模板、历史、批处理 | 高 |
| Duo | 批量效果 `Duo 资源` | `/api/duo/*` | 资源缓存、FFmpeg、运行开关 | 高 |

### C. 账户与设置

| 功能 | 前端入口 | 关键 API | 关键依赖 | 当前风险 |
|---|---|---|---|---|
| 软件设置 | 工作台 `软件设置` | `/api/settings` `/api/user/config` | 本地设置、服务配置、目录配置 | 高 |
| 账户中心 | 工作台 `账户中心` | `/api/user/info` `/api/user/points/overview` `/api/license/*` | 登录态、积分、授权 | 中 |
| 管理后台 | `/admin` | `/api/admin/*` | 管理员权限、配置项、统计项 | 中 |

## 五、阶段推进

### 阶段 1：全量能力盘点与封包范围冻结

目标：
- 确认所有功能都进入封包
- 为每个功能建立“入口、接口、依赖、风险”画像

本阶段产出：
- 当前文档
- 功能依赖总表
- 阻塞问题列表

完成标准：
- 不再对功能边界有歧义
- 后续修复全部按模块推进

### 阶段 2：设置体系收口

目标：
- 所有全局配置统一归属
- 同一配置只保留一个主入口

最终建议的设置结构：

1. 工作台设置
- 自动发现草稿
- 自动恢复上次草稿
- 默认处理策略

2. 路径与目录
- 草稿目录
- 默认导出目录
- 默认素材保存目录

3. 服务设置
- 采集服务
- AI 漫剧服务

4. AI 账号管理
- OpenAI
- 即梦
- 火山 TTS
- 其他兼容服务

处理事项：
- 移除或并入旧 [settings_page.html](/E:/JianYingApi/VideoFactory/app/templates/user/settings_page.html)
- 将 `OpenClaw` 配置从 AI 漫剧页面剥离，归到统一设置
- 业务页只保留“执行参数”，不再承担“保存全局配置”

完成标准：
- 用户对每类配置只有一个明确入口
- 配置保存后全局生效

### 阶段 3：功能可用性修复

目标：
- 逐模块修通，不做零散补丁

#### 3.1 AI 账号管理

修复重点：
- provider 初始化与兜底
- 加载、保存、编辑、删除、测试闭环
- provider 为空时的产品化提示

#### 3.2 AI 成片

修复重点：
- 账号选择与 provider 映射
- 未配置账号时的引导
- 结果轮询与素材回流

#### 3.3 AI 漫剧

修复重点：
- `OpenClaw` 从技术概念改成业务配置项
- 明确 `未配置 / 不可达 / 关闭开关 / 参数缺失` 四种状态
- 生成、模板、历史、批处理链路回归
- 梳理“角色图、脚本、素材”哪些是必填，哪些是选填

#### 3.4 Duo

修复重点：
- 资源状态、缓存状态、FFmpeg 状态显示一致
- 开关关闭时明确禁用，不留假入口

#### 3.5 核心处理链路

修复重点：
- 批量混剪
- 批量效果
- 批量分割
- 片段微调
- 批量导出
- 素材获得

完成标准：
- 每个模块都具备“能否使用”明确状态
- 每个模块关键主链路可跑通

### 阶段 4：页面结构整理

目标：
- 在不重做整体骨架的前提下，整理为可封包交付态

处理重点：
- `软件设置` 变成真正的配置中心
- AI 漫剧从“技术调试页”改成“用户业务页”
- 统一标题层级、卡片密度、错误状态、空状态
- 删除重复入口和多处保存

完成标准：
- 同类页面结构一致
- 配置和执行职责清楚

### 阶段 5：运行开关与封包配置统一

目标：
- 代码、文档、打包配置一致

要统一的内容：
- 全功能 EXE 默认开关值
- 运行开关关闭时的页面表现
- 文档与实际行为一致

完成标准：
- 配置、文档、页面行为不再冲突

### 阶段 6：自检

目标：
- 由我先完成一轮集中自检，不让用户测试半成品

自检维度：
- 导航切换
- 设置保存与回读
- AI 账号管理
- AI 成片
- AI 漫剧
- Duo
- 素材获得
- 批量混剪
- 批量效果
- 批量分割
- 片段微调
- 批量导出
- 账户中心
- 管理后台
- 运行开关

完成标准：
- 输出“通过 / 阻塞 / 可接受小问题”清单

### 阶段 7：用户集中测试

目标：
- 用户只测试一个相对稳定版本

方式：
- 按最终测试清单集中测试
- 不再穿插零散返修

完成标准：
- 用户确认主流程通过
- 阻塞问题清零

### 阶段 8：封包

前置条件：
- 阶段 1 到阶段 7 全部完成
- 我自检通过
- 用户测试通过
- 封包配置固定

## 六、当前阻塞项清单

按优先级排序：

1. `AI 账号管理` provider 数据与可用性兜底未确认
2. `AI 漫剧` 服务配置仍在业务页中，未并入统一设置
3. 旧设置页 [settings_page.html](/E:/JianYingApi/VideoFactory/app/templates/user/settings_page.html) 与工作台设置存在职责重叠
4. 运行开关默认值与历史文档不一致
5. 封包前统一回归清单仍需按这次整理结果重写

## 七、接下来执行顺序

下一轮开始按下面顺序实施：

1. 阶段 2：设置体系收口设计与落地
2. 阶段 3：AI 账号管理可用性修复
3. 阶段 3：AI 漫剧与 OpenClaw 链路整理
4. 阶段 3：Duo 与素材获得依赖状态整理
5. 阶段 4：页面结构整理
6. 阶段 5：运行开关与封包配置统一
7. 阶段 6：集中自检
8. 阶段 7：用户集中测试
9. 阶段 8：封包
