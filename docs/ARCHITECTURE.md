# PaperNest 架构

本文件定义模块边界、依赖方向和通用约定。数据格式见 `DATA_MODEL.md`，旧功能对照见 `LEGACY_MAP.md`，各阶段的落地细节见 `specs/`。三者冲突时以 `DATA_MODEL.md` 为准，其次本文件。

## 1. 总体形态

- 名称：**PaperNest**，旧系统 PaperTrail（v1）的重写版，原计划名"PaperTrail 2.0"。旧仓库 `Wiolic/PaperTrail` 保留给 v1，新仓库为 `Wiolic/PaperNest`。所有标识统一用新名：包与命令 `papernest`、环境变量前缀 `PAPERNEST_`、库配置 `papernest.toml`、库内目录 `.papernest/`、凭据服务名 `papernest`、错误基类 `PaperNestError`。文中提到"旧系统""旧库"时仍指 PaperTrail v1 及其路径 `D:\Desktop\Reference\PaperTrail`。
- 一个 Python 包 `papernest`（Python ≥ 3.11），MIT 许可。
- 软件与数据分离：软件安装在系统里；"文献库"是用户选定的一个文件夹（下称库）。一个进程同一时刻只打开一个库。
- 四个入口共用同一服务层，任何功能都必须先是一个服务函数，再被入口暴露：
  - Web UI：浏览器里的单页应用，只通过 REST API 工作。
  - REST API：`papernest serve` 启动的本机 HTTP 服务。
  - CLI：`papernest <命令>`，全部支持 `--json`。
  - MCP server：`papernest mcp`，供 agent 调用。

## 2. 分层与依赖方向

```
interfaces/   api  cli  mcp  web(前端构建产物)
     │  只调用 services，不直接碰 core 的写操作
services/     ingest dedupe si_pairing review acquire discovery citations topics
              performance regenerate exports maintenance doctor word jobs
     │  调用 adapters 和 core
adapters/     llm crossref openalex unpaywall pdf_text secrets browser
     │  只依赖 core.models 和第三方库，互不依赖
core/         models note_io library index state vocab citekey textsim
              不依赖上面任何一层，不做网络访问
```

规则：

- 依赖只能向下。`core` 不 import `adapters`/`services`；`adapters` 之间不互相 import。
- 入口层不含业务逻辑：参数解析、调服务、格式化输出，仅此而已。
- 所有对外部世界的访问（网络、LLM、Word、浏览器、系统凭据）都在 `adapters/` 或 `services/word`，并以 Protocol 接口注入服务，测试里用假实现替换。
- `papernest.migrate` 是独立的一次性工具，只依赖 `core`。

## 3. 目录结构

```
papernest/                      仓库根
  pyproject.toml  uv.lock  README.md  LICENSE  CLAUDE.md
  src/papernest/
    __init__.py  __main__.py
    core/        models.py note_io.py library.py index.py state.py
                 vocab.py citekey.py textsim.py errors.py
    adapters/    llm.py crossref.py openalex.py unpaywall.py
                 pdf_text.py secrets.py browser.py http.py
    services/    <上面列出的每个服务一个模块>  context.py
    prompts/     <每个 LLM 任务一个模块：system 模板 + pydantic 返回模型>
    interfaces/  api/ (app.py routers/) cli/ (main.py commands/) mcp/ (server.py)
    migrate/     legacy.py legacy_parse.py report.py verify.py
    web_dist/    前端构建产物（打包进 wheel，不进 git）
  web/           前端源码 (React + TypeScript + Vite)
  tests/         unit/ integration/ fixtures/
  docs/          PLAN.md ARCHITECTURE.md DATA_MODEL.md LEGACY_MAP.md STATUS.md specs/
  packaging/     PyInstaller 与 Inno Setup 配置（阶段 11）
```

## 4. 核心层职责

| 模块 | 职责 |
|---|---|
| `models` | pydantic v2 模型：`Paper`（frontmatter）、`Note`（Paper + 正文各节）、`Attachment`、`PerformanceRow`、`ReviewItem`、`Job` 等。所有校验规则集中在这里。 |
| `note_io` | 笔记文件的读与写。读用 YAML 解析器，写用确定性输出（字段顺序固定、LF、UTF-8 无 BOM）。同一份 `Note` 写出的字节永远相同。 |
| `library` | 库的目录布局、路径计算、打开与创建、`papernest.toml` 读写、原子写（临时文件 + `os.replace`）、库级写锁、回收区。按 citekey 找文件一律精确匹配，禁止前缀通配。 |
| `index` | SQLite 索引（含 FTS5）。可随时删除重建；按笔记文件的大小 + mtime + 内容哈希做增量同步。只读查询接口供服务层使用。 |
| `state` | 不可重建的运行状态：任务、审核队列、入库台账（以源文件 sha256 为键）、扫描水位、LLM 用量。 |
| `vocab` | 标签词表、期刊表（全名、缩写、别名、是否顶刊）、表征方法词表、查新分类规则的加载、校验与归一化。 |
| `citekey` | 生成（年份-期刊缩写-提炼标题）、校验、撞名加后缀。 |
| `textsim` | 标题与文件名的归一化和相似度。全系统只有这一份实现，阈值来自库配置。 |

## 5. 适配层

| 模块 | 说明 |
|---|---|
| `llm` | OpenAI 兼容协议客户端。两个档位：`extract`（便宜，做结构化抽取）与 `summarize`（强，写给人看的内容与判断），模型名来自库配置。统一提供：超时、指数退避重试、并发上限、用量记录；`complete_json(tier, system, user, schema)` 用 pydantic 模型校验返回，校验失败带着错误信息重试一次，仍失败抛 `LLMOutputError`。 |
| `crossref` `openalex` `unpaywall` | 基于共享的 `http` 模块（httpx、礼貌限速、磁盘缓存到 `.papernest/cache/`）。联系邮箱从配置读，默认不带。 |
| `pdf_text` | PDF 文本抽取（pypdfium2）与 docx 文本抽取。返回文本 + 是否疑似扫描件。 |
| `secrets` | 通过 `keyring` 读写系统凭据库。环境变量 `PAPERNEST_LLM_API_KEY` 优先。任何地方都不把密钥写入库目录、日志或任务记录。 |
| `browser` | Playwright 驱动系统自带 Edge（`channel="msedge"`，持久化用户目录在 `.papernest/browser/`）。只提供"打开登录窗口""带会话取回一个 URL 的 PDF"两件事。 |

## 6. 服务层约定

- 每个服务模块导出若干纯函数，第一个参数是 `ctx: ServiceContext`。`ServiceContext` 持有打开的库、索引、状态库、词表和各适配器实例。入口层负责构造它。
- 耗时操作（涉及 LLM、网络、批量文件）写成任务函数：`def run(ctx, params, job: JobHandle) -> Result`。`JobHandle` 提供 `progress(done, total, message)`、`log(text)`、`check_cancelled()`。
  - API 下由 `services.jobs` 的后台线程池执行，状态落 `state`，可查询、可取消、进程重启后未完成的标记为 `interrupted` 并可续跑。
  - CLI 下同一个函数同步执行，进度打到终端。
- 修改库的操作分两步：`plan_*` 返回将要发生的变更清单（预览），`apply_*` 执行。API 与 CLI 默认只预览，显式确认才执行。
- 写操作在库级写锁内完成；一组相关文件变更先写临时文件，全部成功后再逐个替换；删除一律移动到回收区。
- 需要人判断的情况不抛错、不猜：生成 `ReviewItem` 进审核队列，任务继续处理下一项。裁决由 `services.review.resolve(item_id, decision)` 完成，UI、CLI、MCP 都走它。

## 7. 入口层约定

### REST API

- 前缀 `/api/v1`，FastAPI 自动生成 OpenAPI。只监听 `127.0.0.1`。
- 启动时生成随机会话令牌，注入到前端页面；API 校验令牌与 `Host` 头，防止其他网页跨站调用本机服务。CLI/MCP 不经过 HTTP，不需要令牌。
- 错误统一为 `{"error": {"code": "...", "message": "...", "details": {...}}}`，`code` 取自 `core.errors` 的枚举。
- 耗时操作返回 `202` + `job_id`；进度通过 `GET /api/v1/jobs/{id}/events`（SSE）推送。
- 静态前端由同一服务托管在 `/`。

### CLI

- Typer。命令按名词分组：`papernest library|paper|ingest|review|discover|acquire|cite|topic|export|doctor|word|job|config|serve|mcp|migrate-legacy`。
- 每条命令支持 `--json`（机器可读，stdout 只有一个 JSON 文档）和 `--library <路径>`（否则读环境变量 `PAPERNEST_LIBRARY`，再否则读用户级配置里的默认库）。
- 会修改库的命令默认预览，加 `--apply` 才执行。

### MCP

- 官方 `mcp` Python SDK，stdio 传输。工具与 CLI 命令一一对应，返回结构化 JSON。破坏性工具同样有 `apply` 参数，默认 false。

### Web

- React 18 + TypeScript + Vite。路由用 React Router，数据请求用 TanStack Query。类型从 OpenAPI 生成，不手写。
- 前端不持有业务规则，只展示和收集输入。设计规格在阶段 9 另写。
- 日后做独立窗口：用 pywebview 或 Tauri 加载同一个本机地址即可，前后端代码不变。

## 8. 技术选型

| 用途 | 选择 | 理由 |
|---|---|---|
| 依赖与构建 | uv + hatchling，锁文件进 git | 可复现安装，一条命令建环境 |
| 数据模型 | pydantic v2 | 校验、JSON Schema、OpenAPI 一套搞定 |
| YAML | PyYAML（safe_load + 自定义确定性输出） | 够用且稳定 |
| 索引 | 标准库 sqlite3 + FTS5 | 零额外依赖 |
| 相似度 | rapidfuzz | 比 difflib 快两个数量级，许可宽松 |
| PDF 文本 | pypdfium2 | 旧系统用的 PyMuPDF 是 AGPL，不适合随 MIT 软件分发 |
| HTTP | httpx | 同步异步通用，测试易打桩 |
| LLM | openai SDK（指向任意兼容端点） | DeepSeek 等供应商均兼容 |
| API | FastAPI + uvicorn | OpenAPI 自动生成 |
| CLI | Typer | 与 pydantic 风格一致 |
| 文档导出 | python-docx、openpyxl | 沿用，许可宽松 |
| 引用样式 | citeproc-py + CSL 样式文件 | 真实的期刊样式 |
| Word | pywin32（仅 Windows，可选依赖组 `word`） | COM 自动化 |
| 浏览器 | playwright（可选依赖组 `acquire`，用系统 Edge，不下载浏览器） | 机构登录会话 |
| 凭据 | keyring | Windows 凭据管理器 / macOS 钥匙串 |
| 检查与测试 | ruff（lint + format）、pytest、pyright（basic） | |
| 打包 | PyInstaller 目录包 + Inno Setup | 面向不用命令行的用户 |

## 9. 测试策略

- `tests/unit`：core 与 services 的纯逻辑，不触网、不调 LLM。
- `tests/integration`：在临时目录建一个小库，走完整流程；LLM 与 HTTP 用录制好的回放数据。
- `tests/fixtures/library_small/`：十来篇人工构造的笔记，覆盖各种边界（标题含冒号、带逗号的列表值、`unknown` 年份、撞名后缀、多个 SI）。不使用真实文献的 PDF。
- `LEGACY_MAP.md` 第 5 节的每条回归用例都必须有同名测试。
- 需要真实 Word 或真实浏览器的功能另有手工验收清单，不进 CI。
- CI：GitHub Actions，Windows 与 Linux，Python 3.11 与 3.12。

## 10. 版本与升级

- 软件版本遵循语义化版本，`CHANGELOG.md` 记录。
- 库有独立的 `format_version`（整数）。软件打开库时：版本相同直接用；库较旧则先把 `notes/` 与 `.papernest/state.db` 备份到 `.papernest/backups/<时间戳>/`，再依次执行迁移函数；库比软件新则拒绝打开并提示升级软件。
- 索引库有自己的 `schema_version`，不匹配时直接删除重建。
