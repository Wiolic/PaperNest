# 阶段 3 规格：旧库迁移

执行档位：Sonnet 写工具 → Haiku 在真实库上执行并整理报告 → 架构档（Opus）验收。
前置阅读：`docs/DATA_MODEL.md`、`docs/LEGACY_MAP.md`、阶段 2 的代码。

## 红线

- 旧库（`D:\Desktop\Reference\PaperTrail`）**只读**。迁移工具对旧库的所有访问都以只读方式打开文件；测试里要有一条断言：迁移前后旧库目录的"文件列表 + 大小 + mtime"快照完全相同。
- 不读取 `scripts/.local_config.json`、`.claude/` 下任何文件。
- 新库目标目录必须不存在或为空，否则拒绝执行。

## 1. 命令

```
papertrail migrate-legacy <旧库> <新库> [--apply] [--report <路径>] [--json]
papertrail migrate-legacy --verify <旧库> <新库> [--json]
```

- 不带 `--apply`：只分析，输出报告，不写新库。
- `--apply`：先完整分析；存在"阻断"级问题则停止；否则执行，结束后自动跑一次 `--verify`。

## 2. 模块

`src/papertrail/migrate/`：

- `legacy_parse.py`：旧格式的容错解析（旧 frontmatter 不是合法 YAML，不能用 yaml 整体解析）。
- `legacy.py`：`analyze(old) -> MigrationPlan`、`apply(plan, new) -> None`。
- `report.py`：把 `MigrationPlan` 渲染成 Markdown 与 JSON。
- `verify.py`：`verify(old, new) -> VerifyReport`。

只依赖 `papertrail.core`。不触网、不调 LLM。

## 3. 旧 frontmatter 解析规则

- 以首个 `---` 行到下一个 `---` 行为界。逐行按 `^([^:\s][^:]*?):[ \t]*(.*)$` 取键和值（只在**第一个**冒号处切分；值的匹配不得跨行）。
- 标量值：去首尾空格；若被成对的单/双引号包住则去引号。
- 列表值（`tags`、`keywords`、`authors_full`、`表征方法`、`related`、`si_files`）：值以 `[` 开头、`]` 结尾时，先尝试 `yaml.safe_load`；失败再做"引号感知"的逗号切分（引号内的逗号不切）。走了回退路径的笔记记入报告的"需人工看一眼"清单。
- 未知键：记为阻断级问题（不允许静默丢数据）。

## 4. 字段映射

| 新字段 | 来源与规则 |
|---|---|
| `citekey` | 原样。必须等于文件名，否则阻断。不符合新正则的记为阻断。 |
| `title` | 原样 |
| `authors` | `authors_full`；为空时把旧 `authors` 串按 `;` 切分并去掉 `et al.`，仍为空则 `[]`，记入警告 |
| `year` | 整数；`unknown`、空 → null |
| `journal` | `unknown`、空 → null |
| `doi` | 占位值集合（见 LEGACY_MAP 第 3 节，至少含 `N/A`、`NA`、`unknown`、`none`、空，不区分大小写）→ null；其余走模型的归一化 |
| `volume` `issue` `pages` | null（阶段 4 提供 `papertrail paper enrich` 从 Crossref 补齐） |
| `entry_type` | `article` |
| `type` | 计算→`computational`；实验→`experimental`；计算+实验、实验+计算→`combined`；综述→`review`；其他值 → null 并记入警告 |
| `tags` `keywords` `related` `si_files` | 原样（去首尾空格、去空项、保序去重） |
| `methods` | 方法关键词 |
| `characterization` / `characterization_unmapped` | 旧 `表征方法` 中以 `unmapped:` 开头的项去前缀后进后者，其余进前者 |
| `system` | 体系 |
| `status` | 原样；非法值 → `unread` 并记入警告 |
| `rating` | `★` 的个数；空 → null |
| `added` | 旧 `added` 日期 + 旧笔记文件 mtime 的时分秒（两者日期相同时）；否则 `T00:00:00` |

正文：换行统一为 LF 后**逐字保留**，再按配置的七个小节标题解析为 `sections`。解析后重新输出的正文必须与原正文（LF 归一化、去首尾空白后）完全相等，否则阻断。

## 5. 文件迁移

| 旧 | 新 | 规则 |
|---|---|---|
| `notes/<ck>.md` | `notes/<ck>.md` | 按上面规则重写；写完把文件 mtime 设回旧值 |
| `papers/*` | `papers/*` | 逐字节复制，保留 mtime；扩展名转小写；记录 sha256 |
| `extracted-text/<ck>.txt` | `text/<ck>.txt` | 换行归一化为 LF |
| `topics/*.md` | `topics/*.md` | 复制；`[[ck]]` 不存在的记入警告 |
| `data/performance.csv` | `data/performance.csv` | 见第 6 节 |
| `research_profile.md` | `profile.md` | 复制 |
| `vocab/characterization.yaml` | `vocab/characterization.yaml` | 转成 DATA_MODEL 第 5 节格式 |
| `scripts/tag_vocab.txt` | `vocab/tags.yaml` | 见第 7 节 |
| `scripts/top_journals.txt` | `vocab/journals.yaml` | 见第 7 节 |
| `scripts/.scan_state.json` | `state.db` 的 `scan_watermarks` | 字段 → 行，`history` 原样存 JSON |
| `inbox/*.pdf` 等 | `inbox/` | 复制（不含 `.meta_cache/`） |
| `scripts/.ingest_state.json` | `state.db` 的 `ingest_ledger` | 旧 key 是绝对路径，源文件若仍存在则算 sha256 入账；不存在的跳过并计数 |

**不迁移**：`notes-readable/`、`library.bib`、`INDEX.md`、`KEYWORDS.md`、`exports/`、`scripts/`、`github_upload*/`、`prompts/`、`schema/`、`templates/`、其余状态文件。报告里列出这份清单。

`library.bib` 仅用于交叉核对：bib 条目数与 citekey 集合应与 notes 一致，不一致记入警告。

## 6. performance.csv

- 列名与顺序保持。
- 每行的 `citekey` 若不在新库：尝试把期刊段的 `ACIE` 换成 `AngewChemIntEd` 后再找；找到则改写 `citekey` 与 `row_id`，记入"已修正"；仍找不到的行原样保留并记入警告（doctor 之后会继续报）。
- 行数必须前后相等。

## 7. 词表生成

- `tags.yaml`：先放入 `tag_vocab.txt` 的词（`unreviewed: false`）；再把全库实际用到但不在词表中的 tag 加入（`unreviewed: true`）。报告里按使用次数列出这些词，并用 `textsim` 提示疑似同义的词对（如只差大小写、单复数）。
- `journals.yaml`：遍历全部笔记，按"归一化期刊名"分组，从 citekey 第二段取缩写。一个期刊出现多个缩写时取出现次数最多的，其余写入报告的"期刊缩写冲突"清单（**不改 citekey**）。`top_journals.txt` 里的名字标 `top: true`（名单里有而库里没出现过的期刊也加入，`abbr` 留空并标 `unreviewed: true`）。journal 为 null 的不入表。

## 8. 报告内容

1. 数量总览：笔记、主文件、SI、全文缓存、性能数据行、综述。
2. 阻断级问题（有则不能 `--apply`）。
3. 自动修正统计：frontmatter 引号修复数、type 归一、DOI 占位值清理、unmapped 拆分、performance citekey 修正。
4. 警告清单（逐条带 citekey）。
5. 需要用户决定的事项：词表外标签、期刊缩写冲突、疑似同义标签。
6. 不迁移的内容清单。

## 9. 校验（`--verify`）

全部通过才算成功：

- 新库 citekey 集合 = 旧库 `notes/` 的 citekey 集合。
- `papers/` 文件数相等；每个文件 sha256 相等（文件名不区分扩展名大小写地对应）。
- 每篇笔记能被 `note_io.read_note` 读入且通过模型校验。
- 每篇笔记正文与旧正文相等（LF 归一化、去首尾空白）。
- 每篇的 `title`、`year`、`doi`、`journal`、`tags`、`keywords`、`si_files` 与用旧解析器读出的值按第 4 节规则换算后相等。
- `text/` 文件数相等。
- `performance.csv` 行数相等，表头相等。
- `Index.rebuild()` 的条目数 = 笔记数，`errors()` 为空。
- `doctor` 不报 `note_invalid`、`missing_main_file`、`si_mismatch`。
- 旧库快照（文件列表 + 大小 + mtime）迁移前后一致。

## 10. 测试

- `tests/fixtures/legacy_small/`：仿旧格式的小库（8 篇，虚构内容），覆盖：title 含冒号未加引号、空 `rating:`、`实验+计算`、`unmapped:` 项、`unknown` 年份、DOI 为 `N/A`、带 SI、关键词含逗号、CRLF 换行的文件、performance.csv 含 `ACIE` 旧 citekey 行。
- 对这个小库跑 analyze → apply → verify 全流程。
- 第 3 节解析规则逐条单测，尤其"空值字段不得吞掉下一行"。

## 11. 在真实库上执行（Haiku 会话）

1. `papertrail migrate-legacy "D:\Desktop\Reference\PaperTrail" <新库> --report <仓库外的临时路径>`，把报告的第 2、5 节贴给用户。
2. 有阻断级问题：停下，交回执行档修工具，不要手改数据。
3. 无阻断：经用户同意后加 `--apply`。预期数字：笔记 406、`papers/` 文件 434（其中 SI 28）、全文缓存 406、性能数据 1047 行、综述 3。
4. 跑 `papertrail --library <新库> doctor`，把结果摘要贴给用户。
5. 真实库的报告和数据**不进 git**。

## 12. 验收关口（架构档）

阅读迁移报告与 verify 结果，抽查 10 篇笔记（必须包含：标题含冒号的、`unknown-` 开头的、带 SI 的、有 unmapped 的），确认无数据丢失后，在 `docs/STATUS.md` 记录"阶段 3 通过"，并写阶段 4、5 的规格。
