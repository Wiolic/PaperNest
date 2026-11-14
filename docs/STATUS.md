# 进度日志

最新的记录写在最上面。

## 当前状态

- **已完成**：阶段 0（规格奠基）、阶段 1（工程脚手架）
- **下一步**：阶段 2 第一段（models + note_io + library），执行档 Sonnet，规格 `docs/specs/02-core.md`
- **新文献库位置**：未定。计划默认 `D:\Desktop\Reference\PaperNest-Library`，阶段 3 执行前由用户确认。

## 待用户决定

- 新文献库放在哪。
- 本地仓库文件夹仍叫 `D:\Dev\papertrail`，是否改成 `D:\Dev\papernest`（需在会话外改，改后 `.venv` 要重建）。
- 旧 DeepSeek key 需要轮换（明文存在旧库的 `scripts/.local_config.json` 与 `.claude/settings.local.json`）。

## 待架构档决定

阶段 1 中规格没写清、按最保守做法处理的地方：

1. **React 版本**：ARCHITECTURE 第 7 节写 React 18，而 `npm create vite` 现在默认 React 19。选了 React 18（`react@18`、`@types/react@18`）。另外 npm 上 `typescript` 最新为 7.x、`vite` 为 8.x，均按最新装，构建通过；若要锁主版本需架构档定。
2. **前端手写而非 `npm create vite`**：为避免交互式向导，按 react-ts 模板最小形态手写（单个 `tsconfig.json`，没有模板里的 app/node 双 tsconfig 与 eslint）。ESLint 未引入，规格没提。
3. **`.gitignore`**：仓库已有一份（含 `.env`）。保留 `.env`，补充 `web/dist/`；规格要求的项均已覆盖。
4. **`ruff.toml` 排除 `web/`**：避免 ruff 扫到前端目录。
5. **`ErrorCode` 成员名**：规格只给了字符串值；成员名取值的大写形式（如 `CITEKEY_NOT_FOUND`），基于 `StrEnum`。
6. **错误码到 HTTP 状态的映射**写在 `interfaces/api/app.py` 里（如 `citekey_not_found`→404、`locked`→423、未知→500）；规格只要求"统一处理器"，该映射需架构档确认是否放到 ARCHITECTURE 第 7 节。
7. **wheel 打包**：`pyproject.toml` 用 hatch 的 `artifacts` 把被 gitignore 的 `web_dist` 纳入 wheel；阶段 11 打包时需验证。
8. **`serve`**：`--no-browser` 缺省时用 1 秒定时器打开浏览器；会话令牌与 Host 校验（ARCHITECTURE 第 7 节）阶段 1 未做。
9. `tests/fixtures/.gitkeep` 占位，保证目录入库。
10. CI 工作流未在 GitHub 上实际跑过（未 push）；Action 版本号（checkout@v4、setup-uv@v5、setup-node@v4）是按记忆写的，首次 push 后需看结果。CI 的 Node 用 `lts/*`，本机是 Node 26.13.1（winget 的"LTS"包）。

## 相对 `PLAN.md` 的调整

- 卷期页的 Crossref 补齐从"迁移时做"改为阶段 4 的独立命令 `papernest paper enrich`，因为迁移工具不触网，这样迁移结果可离线复现和校验。
- PDF 文本抽取从 PyMuPDF 换成 pypdfium2：PyMuPDF 是 AGPL 许可，不适合随 MIT 软件一起分发。

## 记录

### 定名 PaperNest（架构档）

- 用户定名 **PaperNest**，取代"PaperTrail 2.0"。全部文档、代码、包名、命令、环境变量前缀、库内文件名已改（规则见 `ARCHITECTURE.md` 第 1 节）。指向旧系统的引用（旧库路径、旧启动器文件名）保持原样。
- git 身份定为 `Eggy`（仓库级），历史提交作者已全部改写为 Eggy。
- 新建公开仓库 `https://github.com/Wiolic/PaperNest` 并推送 `main`。旧仓库 `Wiolic/PaperTrail`（v1）未动。用户授权范围：只 push；不发版、不改仓库设置、不强推。

### 阶段 1 — 工程脚手架（执行档）

产出：规格第 1 节全部文件；环境新装 uv 0.13.8、Node 26.13.1（npm 11.20.0），均经用户同意。验收清单已逐条跑通（浏览器渲染未目测，用 HTTP 取回页面与 API 验证）。

踩坑：

- 新装的 uv/Node 不在已开终端的 PATH 里，需刷新 PATH 或重开终端。
- 构建出 `web_dist` 后，测试里在 `create_app()` 之后加路由会被 `/` 的静态挂载盖住；错误处理器测试因此先把 `WEB_DIST` 指到不存在的目录。
- 初次写 `.gitignore` 误覆盖了已有文件的 `.env` 行，已补回。

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
