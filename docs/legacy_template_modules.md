# 遗留模板模块清单

## 判断

当前产品方向是 EXE 本地运行，用户直接读取本机剪映草稿并处理。

在这个方向下，“上传模板到服务端并存入模板库”不再是主链路，应降级为遗留模块，而不是继续扩展。

## 应保留的主链路

- 用户本机选择 `draft_path`
- 本机解析草稿内容
- 本机选择素材目录
- 本机执行批量替换/效果/导出
- 服务端只保留账号、授权、配额、日志等核心业务数据

## 遗留模块范围

- `app/models/template_model.py`
  - 服务端模板库记录
- `app/services/jianying/batch_service.py`
  - 依赖 `template_id` 的批量任务入口
- `app/views/api.py`
  - `/api/generate` 的 `template_id` 提交流程
  - `/api/template/<id>/configure`
  - `/api/template/<id>/tracks`
- `app/uploads/templates/`
  - 服务端保存的模板副本
- `app/views/admin.py`
  - 与模板库管理强相关的逻辑

## 处理建议

1. 先保留兼容，不立即硬删
2. 新功能一律只走 `draft_path`，不再新增 `template_id` 入口
3. 前端逐步移除“上传模板/模板库”入口
4. 等 EXE 本地链路稳定后，再删除模板上传与服务端模板库存储

## 删除前置条件

- 本地 `draft_path` 主链路稳定
- 冒烟测试不再依赖 `template_models`
- 前端没有入口再调用模板上传/模板配置接口
- 数据库和任务链路不再要求 `template_id`
