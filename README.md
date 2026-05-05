# JianYingvideo

剪映/CapCut 草稿自动化与桌面打包工具，支持新版剪映草稿结构，并接入 AI 生图模型。

JianYingvideo 是一套面向短视频批量生产、剪映草稿自动化、AI 漫剧/生图工作流和会员化运营的 Windows 桌面应用源码。项目保留了草稿读写、批量处理、用户工作台、管理员后台、授权/CDK、配额管理和桌面打包链路，适合作为剪映自动化工具、商业化桌面软件或二次开发基础。

## 核心优势

- **新版剪映草稿适配**：围绕剪映/CapCut 草稿结构做读写、替换、生成和导出，适合持续适配新版草稿结构。
- **批量生产能力**：支持批量素材替换、顺序/随机素材池、动画、转场、特效、字幕/文本、音频处理、关键帧和草稿导出等自动化能力。
- **AI 工作流接入**：已包含 AI 账号管理、生图/漫剧相关入口，可扩展文案、分镜、图片生成和 AI 视频生产流程。
- **桌面端交付链路**：内置 Windows EXE/安装包打包脚本、Inno Setup 模板和发布检查，便于从源码走到可分发桌面包。
- **MCP/API 扩展能力**：保留 MCP 与 HTTP API 能力，方便接入外部自动化、批处理服务或自定义工具链。
- **商业化运营基础**：包含用户、角色、VIP、次数、CDK、设备绑定、站点配置、公告和审计等运营能力。

## 主要功能

### 剪映草稿自动化

- 创建、读取、替换和导出剪映/CapCut 草稿。
- 支持本地草稿目录、素材目录、导出目录等路径配置。
- 支持视频、音频、文本、特效、转场、动画、关键帧等草稿元素处理。
- 支持批量生成草稿，降低重复剪辑和批量混剪的人工作业量。

### AI 生图与漫剧工作流

- AI 账号管理，支持保存、启用、测试不同模型服务配置。
- AI 漫剧、生图、分镜和素材目录工作流可作为二次开发基础。
- 可结合草稿生成能力，把 AI 生产的脚本、图片或素材进一步落到剪映草稿中。

### 用户工作台

- 面向普通用户的桌面工作台入口。
- 支持草稿处理、素材管理、生成记录、账户中心、软件设置等常用操作。
- 支持会员状态、剩余次数、邀请关系、授权激活等用户侧信息展示。

## 商业化与 Admin 能力

项目内置一套适合商业化桌面软件的后台与授权基础：

- **用户与权限**：用户登录、角色区分、管理员权限校验。
- **次数与 VIP**：用户剩余次数、总生成量、VIP 到期时间、单用户和批量配额调整。
- **License/CDK**：支持激活、联网校验、反激活、授权状态查询和设备绑定。
- **运营配置**：站点名称、Logo、下载地址、用户协议、公告等配置可由后台维护。
- **API 管理**：API Key、调用配额、权限模板、调用审计、使用记录和效果日志。
- **远程鉴权模式**：桌面端可运行在 remote-auth 模式；该模式下本地后台默认关闭，应使用服务端后台统一管理用户、授权和运营配置。

## 公开源码边界

公开仓库包含源码、文档、示例配置和打包脚本，便于审阅和二次开发：

- `app/`、`blanks/`、`migrations/`、`packaging/`、`scripts/`、`docs/`
- `env.presets/*.example`
- `desktop_app.py`、`run.py`、`run_worker.py`、`runtime_paths_shared.py`
- 内置依赖源码 `app/utils/JianYingApi/`

公开仓库不包含本机私密和运行时状态：

- `.env`、真实 release preset、数据库、日志、缓存、用户上传内容
- `venv/`、`venv312/`、`build/`、`dist/`
- `runtime_tools/`、本地第三方二进制工具、私有服务配置和打包产物

安装包、便携包和 `installer_manifest.json` 应通过 GitHub Releases 发布，不提交到 Git 历史。

## 运行与打包

打包流程见 `docs/windows_packaging.md`。基础检查和桌面包构建命令示例：

```powershell
venv\Scripts\python.exe scripts\prepackage_check.py
venv\Scripts\python.exe scripts\build_desktop_bundle.py --preset env.presets\desktop_full.env.example --name ZhiyingShijie
```

正式发布时请使用本机私有 release preset 填入生产配置，并确保该 preset 不提交到公开仓库。公开仓库只保留 `.example` 示例配置。

## Release 附件

桌面安装包建议通过 GitHub Releases 发布，例如：

- `ZhiyingShijie_<version>.exe`
- 可选便携包 `ZhiyingShijie_<version>_portable.zip`
- `installer_manifest.json`

每次发布应保证 Release 说明与 manifest 中的提交、分支、构建时间和 `git_dirty` 状态一致。

## 鸣谢

本项目在剪映草稿结构理解、自动化能力和工具链整理过程中，参考并复用了部分开源项目的思路与代码，在此特别感谢：

- [JianYing-Automation/JianYingApi](https://github.com/JianYing-Automation/JianYingApi)：第三方剪映 API 项目，当前仓库内置的 `app/utils/JianYingApi/` 源码来源于该项目，并保留其 MIT License。
- [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)：Python 剪映草稿生成与编辑工具，本项目的 MCP 草稿导出、效果枚举和部分草稿能力接入参考了该生态。

感谢以上项目作者和社区对剪映/CapCut 自动化方向的探索。

## License

本项目使用 MIT License。你可以使用、复制、修改、分发和商用本项目代码，但需要保留原始版权声明和许可证文本。
