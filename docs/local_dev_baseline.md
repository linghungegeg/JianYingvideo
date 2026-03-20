# 本机开发基线

## 目标

在本机稳定复现以下流程：

1. 启动 Flask 服务
2. 登录系统
3. 提交批量混剪 / 分割 / 微调 / 导出任务
4. 查询任务结果
5. 验证本地草稿与本地素材链路

## 当前代码基线

- 应用入口：`run.py`
- Flask 装配：`app/__init__.py`
- 用户工作台：`app/templates/user/index.html`
- 主业务 API：`app/views/api.py`
- 本地任务执行：`app/tasks.py`

## 当前已确认的运行方式

- 主链路不再依赖 `Redis + worker`
- 批量混剪、分割、微调、导出都走本地后台执行
- 服务端主要负责账号、授权、次数、用户配置
- 当前推荐主业务数据库使用 MySQL
- `sqlite:///data-dev.sqlite` 仅适合作为临时开发回退

## 推荐本机依赖

- Python 虚拟环境：`venv`
- MySQL
- FFmpeg
- 剪映 / CapCut 草稿目录
- 本地素材目录

## 推荐 `.env`

至少配置：

```env
SECRET_KEY=dev-secret
VIDEOFACTORY_KEY_ENCRYPTION_KEY=base64-32-byte-urlsafe-key
DATABASE_URL=mysql+pymysql://USER:PASSWORD@localhost:3306/video_factory
DEFAULT_USER_QUOTA=5
```

如果只是临时脱离 MySQL 做纯本机调试，可改为：

```env
DATABASE_URL=sqlite:///data-dev.sqlite
```

## 启动顺序

1. 启动 MySQL
2. 初始化数据库迁移
3. 启动 Flask
4. 跑运行时自检
5. 跑核心冒烟

## 常用命令

```powershell
venv\Scripts\python.exe -m flask db upgrade
```

```powershell
venv\Scripts\python.exe run.py
```

```powershell
venv\Scripts\python.exe scripts\runtime_selfcheck.py
```

```powershell
venv\Scripts\python.exe scripts\core_flow_smoke.py
```

## 当前建议

- 本机开发优先验证 `/user` 工作台链路，不再围绕旧首页和旧草稿中心开发
- 有 FFmpeg 时优先把分割、主轨片段导出、微调一起测掉
- 封包前重点看：功能是否完整、入口是否齐、运行依赖是否可随 EXE 一起打包
