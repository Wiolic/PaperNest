# 进度日志

最新的记录写在最上面。

## 当前状态

- **已完成**：阶段 0（规格奠基）
- **下一步**：阶段 1（工程脚手架），执行档 Sonnet，规格 `docs/specs/01-scaffold.md`
- **新文献库位置**：未定。计划默认 `D:\Desktop\Reference\PaperTrail-Library`，阶段 3 执行前由用户确认。

## 待用户决定

- git 提交身份（本机未配置全局 `user.name` / `user.email`；阶段 0 的提交用了仓库级占位身份 `PaperTrail Dev`，可随时改）。
- GitHub 仓库名、公开还是私有、何时首次 push。
- 新文献库放在哪。
- 旧 DeepSeek key 需要轮换（明文存在旧库的 `scripts/.local_config.json` 与 `.claude/settings.local.json`）。

## 待架构档决定

（暂无）

## 相对 `PLAN.md` 的调整

- 卷期页的 Crossref 补齐从"迁移时做"改为阶段 4 的独立命令 `papertrail paper enrich`，因为迁移工具不触网，这样迁移结果可离线复现和校验。
- PDF 文本抽取从 PyMuPDF 换成 pypdfium2：PyMuPDF 是 AGPL 许可，不适合随 MIT 软件一起分发。

## 记录

### 阶段 0 — 规格奠基（架构档）

产出：

- `docs/PLAN.md`：总路线图
- `docs/ARCHITECTURE.md`：分层、模块、约定、选型
- `docs/DATA_MODEL.md`：库格式 v1
- `docs/LEGACY_MAP.md`：旧功能对照与回归用例（由 Sonnet 子代理阅读旧代码后编写）
- `docs/specs/01-scaffold.md`、`02-core.md`、`03-migration.md`
- `CLAUDE.md`：开发约定

本机环境：git 2.55、Python 3.12.10、gh 已安装；**uv 与 Node 未安装**，阶段 1 第一步要装。

旧库中新增了一个文件 `REBUILD_PLAN.md`（计划副本，经用户同意）。

后续阶段的规格由谁在何时写：

| 规格 | 何时写 |
|---|---|
| 04 适配层、05 入库流水线 | 阶段 3 验收关口 |
| 06 API/CLI/MCP、07 知识功能 | 阶段 5 验收关口 |
| 08 查新与下载、09 前端设计 | 阶段 7 结束后 |
| 10 Word、11 打包 | 阶段 9 结束后 |
