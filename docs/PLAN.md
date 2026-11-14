# PaperNest 重建计划

> 本项目原计划名"PaperTrail 2.0"，阶段 1 后正式定名 **PaperNest**。下文"现有 PaperTrail""旧系统"指 v1。

## Context（为什么重建）

现有 PaperTrail 是 30 多个零散脚本 + 一个 982 行的 Streamlit 面板，功能齐全但已到维护极限。调研确认的现状：

- **数据很干净，值得保留**：406 篇文献，`notes/`、`papers/`（含 28 个 SI）、`extracted-text/`、`library.bib` 四方 citekey 完全对齐；另有 1047 行性能数据、3 篇主题综述、1 条查新记录。
- **代码不值得保留**：frontmatter 解析有 7 份实现、bib 解析 7 份、标题查重 6 份；`batch_ingest.py` 同时是脚本、格式库和 prompt 仓库；零测试、无依赖锁定、无事务。
- **已有实际损坏**：406 篇里 71 篇 frontmatter 不是合法 YAML；`INDEX.md` 显示"共 0 篇"；`performance.csv` 有 28 行指向已改名的旧 citekey；67 个标签不在词表里；删除脚本的前缀匹配会误删撞名文献。
- **依赖 Claude Code**：入库的查重/DOI/SI 判断、扩充查新的 WebSearch 都只能在对话里完成。
- **安全问题**：DeepSeek key 明文存在 `scripts/.local_config.json` 和 `.claude/settings.local.json`，**重建前先轮换这个 key**。

目标：重写成一个可安装、可升级、可被 API 和 agent 完整驱动的正式软件，旧数据无损迁入。

## 已确认的决策

| 问题 | 决定 |
|---|---|
| 界面 | 本地网页应用，前端完全重写；前后端只通过 HTTP API 通信，日后套桌面窗口壳不需要改代码 |
| 安装对象 | 完全不碰命令行的人 → Windows 安装包（双击安装）；同时发 PyPI 供开发者和 agent 用 |
| 数据真源 | Markdown 笔记文件（严格 YAML）+ PDF；SQLite 只是可随时重建的索引 |
| Word 引用 | 升级为文档内嵌身份（内容控件承载 citekey），可切换样式并全文重排 |
| 新增功能 | 用学校账号直接下载文献（见"机构下载"一节） |

## 目标架构

**一个 Python 包 `papernest`，四个入口共用同一服务层**：

```
界面层   Web UI (React+TS+Vite)   CLI (Typer, --json)   MCP server   REST API (FastAPI, OpenAPI)
            └──────────────┴───────────────┴──────────────┘
服务层   ingest · dedupe · si_pairing · acquire · discovery · citations · topics
         performance · exports · word · doctor · jobs(后台任务:进度/取消/续跑)
适配层   llm(OpenAI 兼容,多供应商) · crossref · openalex · unpaywall · pdf_text · keyring
核心层   models(pydantic) · note_io(严格 YAML) · library(原子写+文件锁) · index(SQLite+FTS5) · vocab
```

要点：

- **代码与数据分离**。软件装在系统里；"文献库"是用户选的一个文件夹，含 `papernest.toml`（配置 + 库格式版本号）。升级软件不动数据；库格式变更走带自动备份的迁移。
- **六处同步消失**。真源只有 `notes/<citekey>.md`、`papers/`、`text/`。`library.bib`、`INDEX.md`、`KEYWORDS.md`、`notes-readable/` 全部变成按需导出，现有的 `rename_*`、`resolve_duplicate`、`sync_index_count`、`render_readable_notes` 和大半个 `check_library.sh` 不再需要对应物。
- **领域内容变成库级配置**。标签词表、期刊缩写表 + 顶刊名单、表征方法词表、课题背景、查新分类规则都放进库的 `vocab/` 和 `profile.md`，软件本身不含电催化内容，别人装上即可套自己的领域。
- **"人工判断"变成审核队列**。入库时查重、DOI 核实、SI 配对有把握的自动通过，存疑的进队列，由用户在界面里或 agent 通过 MCP 裁决。这样不再需要 Claude Code 在场。
- **查新不再靠 WebSearch**。改用 OpenAlex API 按"期刊 + 时间窗 + 关键词"检索（可分页穷举，比每次 10 条的网页搜索全得多），Crossref 核验，记录扫描水位。
- **LLM 供应商无关**。统一客户端走 OpenAI 兼容协议（DeepSeek 为默认预设），"抽取用便宜模型、总结用强模型"保留为两个可配置档位；所有返回用 pydantic 校验，统一重试、限流和费用记录。
- **密钥进系统凭据库**（Windows Credential Manager），不再落明文。
- **破坏性操作可撤销**。删除、合并、改名先进库内回收区，全部支持预览。
- **Word**：COM 连接已打开的文档，引用标记是内容控件（tag 里存 citekey），References 也在内容控件里；样式用 CSL（citeproc-py），因此 Nature / Angewandte / GB/T 7714 是真实样式而非近似。需要卷期页，迁移时从 Crossref 补齐。仅 Windows。
- **打包**：PyInstaller 目录包 + Inno Setup 安装器，GitHub Actions 打 tag 自动出包；应用内检查新版本。

### 机构下载（新功能）的边界

- 顺序：先查开放获取（Unpaywall），没有再走机构订阅。
- 登录方式：软件打开一个独立浏览器窗口（调用系统自带的 Edge，Playwright 持久化配置目录），**用户自己在窗口里登录学校统一认证**；软件只复用登录后的会话，不保存、不经手密码。验证码由用户自己完成。
- 合规：仅限学校已订阅的内容；用户发起、逐篇下载、带限速，不做批量爬取（出版商条款禁止系统性下载，违规可能导致全校 IP 被封）。下载失败就把条目留在"待下载"清单并给出链接。
- 下载成功后直接进入入库流水线。

### 旧数据迁移

`papernest migrate-legacy <旧库> <新库>`，**只复制，旧库一个字节不动**（沿用现有红线）。先出预览报告，确认后执行：

- citekey 全部原样保留（含 5 个 `unknown-` 开头的）。
- frontmatter 重写为合法 YAML；4 个中文键改英文（`类型→type`、`方法关键词→methods`、`表征方法→characterization`、`体系→system`），界面仍显示中文。
- 顺手修复：`实验+计算` 归一为 `计算+实验`；`unmapped:` 前缀改为单独字段；`performance.csv` 里 28 行旧 citekey 改正；67 个词表外标签列出供用户决定收编或合并。
- 七节正文、`extracted-text`、topics、扫描水位原样带入；卷期页从 Crossref 补齐。
- 验收：406 / 434 / 28 / 1047 四个数字一致，PDF 逐个哈希比对，正文逐篇文本比对。

## 开发方法：三档模型分工

| 档位 | 模型 | 负责 |
|---|---|---|
| 架构档 | Opus 5.5 | 写规格文档、定接口与数据格式、阶段验收评审 |
| 执行档 | Sonnet 5.5 | 按规格写代码和测试 |
| 杂务档 | Haiku 5.5 | 测试样例、文档、跑迁移和报告等机械工作 |

执行档会话内部可以再把搜索、批量修改派给 Haiku 子代理。

**交接靠仓库里的文件，不靠对话记忆**。新仓库里固定四样东西：

- `docs/PLAN.md`：本计划（路线图）。
- `docs/specs/NN-*.md`：每阶段的规格，含接口定义和验收清单。架构档写，执行档照做。
- `docs/STATUS.md`：进度日志。每次会话结束时更新：做完什么、没做完什么、踩了什么坑。
- `CLAUDE.md`：开发约定（目录结构、测试命令、提交规范、红线）。

**每次会话的固定收尾**：跑测试 → 提交 → 更新 `STATUS.md` → 输出下一步要复制的指令（含该用哪一档模型）。上下文用到一半以上而阶段未完，就提前收尾并给出"续做"指令。

## 阶段路线

每个阶段一到数个对话。带 ★ 的是架构档验收关口，不通过不进入下一段。

| 阶段 | 档位 | 内容 | 完成标志 |
|---|---|---|---|
| 0 规格奠基 | 架构 | 建仓库；写 `ARCHITECTURE.md`、`DATA_MODEL.md`（库布局、frontmatter schema、索引表结构）、`LEGACY_MAP.md`（旧功能→新模块对照，旧 bug 列为回归用例）、`CLAUDE.md`、阶段 1–3 的规格 | 文档齐全，用户过目 |
| 1 工程脚手架 | 执行 | uv + pyproject、src 布局、ruff、pytest、GitHub Actions（Windows + Linux）、CLI/API/前端空壳 | CI 绿 |
| 2 核心层 | 执行（样例由杂务档） | models、note_io、library、index、vocab、citekey 生成、doctor 检查 | 单测覆盖旧 bug 回归用例 |
| 3 数据迁移 ★ | 执行 → 杂务跑 → 架构验收 | `migrate-legacy`，预览报告，在真实库上执行 | 四个数字一致，哈希与正文比对通过 |
| 4 适配层 | 执行 | LLM 客户端、Crossref/OpenAlex/Unpaywall（带缓存）、PDF 抽取、凭据存储 | 录制回放测试通过 |
| 5 入库流水线 ★ | 架构写规格 → 执行 | 后台任务框架、查重三层、SI 配对、审核队列 | 用旧库 20 篇 PDF 重新入库，结果与现有笔记同等质量 |
| 6 API / CLI / MCP | 执行 | 全部服务暴露为 REST、命令行和 MCP 工具；任务进度推送 | 不开界面，仅用 CLI 和 MCP 各走通一次完整入库 |
| 7 知识功能 | 执行（prompt 由架构档审） | 引文献、主题综述 + docx、性能数据抽取、笔记重生成、导出（bib/RIS/xlsx/文件夹）、合并/改名/删除 | 每项与旧脚本在同一输入上对比 |
| 8 查新与下载 ★ | 架构写规格 → 执行 | OpenAlex 查新 + 扫描水位；Unpaywall + 机构下载 | 重跑"PEM 催化剂"查新，覆盖旧结果；一篇订阅文献端到端下载入库 |
| 9 前端 | 架构出设计规格 → 执行 | 总览、文献库、阅读窗格、入库与审核、引文献、综述、查新与下载、Word、设置、任务 | 见下方体验清单 |
| 10 Word v2 | 架构写规格 → 执行 | 内容控件、CSL 样式、重排、自动找引用位置 | 手工验收清单全过 |
| 11 打包发布 | 执行（文档由杂务档） | 安装包、首次运行向导、更新检查、中英文使用说明 | 在一台干净 Windows 上双击装好并打开库 |
| 12 总验收 ★ | 架构 | 对照 `LEGACY_MAP.md` 逐项核对；切换；旧库归档不删 | 清单全绿 |

前端必须保留的体验（来自现有面板反复打磨的点）：右侧阅读窗格（点空白处关闭、滑入动画）、操作后不丢当前页面和滚动位置、卡片信息密度与笔记/PDF 两个按钮、PDF 用系统阅读器打开、"共 N 篇符合条件"计数、拖拽 PDF 入库、课题说明/词表/顶刊名单可在界面里改、综述编辑时实时校验 `[[citekey]]`、蓝色莫兰迪配色（`#F4F1EC` / `#5B7C99` / `#7B93AB` / `#C4D1DB`）、长任务有进度且可取消。

## 需要读的旧文件（阶段 0 的输入）

- `AGENTS.md`：数据规范与全部踩坑记录
- `scripts/batch_ingest.py`：入库 prompt 字段、查重三层、SI 配对规则
- `scripts/find_citations.py`、`scripts/build_topic_digest.py`、`scripts/extract_performance.py`：各自的 prompt
- `scripts/word_insert_citation.py`：重编号算法
- `scripts/ui/app.py`：界面功能清单
- `vocab/characterization.yaml`、`scripts/tag_vocab.txt`、`scripts/top_journals.txt`、`research_profile.md`

这些只作为需求来源阅读，不复制代码。

## 批准后本次会话要做的事

1. 把本计划存为 `D:\Desktop\Reference\PaperTrail\REBUILD_PLAN.md`，供后续对话读取（旧库里只新增这一个文件）。
2. 输出"阶段 0"的完整可复制指令，并注明用 Opus 5.5 开新对话。

待你定的两个默认值（阶段 0 开始时确认即可）：新代码仓库放 `D:\Dev\papertrail`（避开桌面同步目录）；新文献库放 `D:\Desktop\Reference\PaperNest-Library`。

## 验证

- 每阶段：`uv run pytest` 全过 + 该阶段规格里的验收清单 + CI 绿。
- 迁移：数量、哈希、正文三重比对（阶段 3）。
- 独立性：阶段 6 结束时在未启动 Claude Code 的情况下，仅用 CLI 和 HTTP API 完成入库、检索、引文献。
- agent 可控：用 MCP 客户端调用工具完成一次入库和一次审核裁决。
- 安装：阶段 11 在干净 Windows 环境双击安装并升级一次，库数据不变。
