# PaperTrail 2.0 数据模型（库格式 v1）

本文件是数据格式的唯一权威定义。

## 1. 库目录布局

```
<库>/
  papertrail.toml            库配置 + format_version
  profile.md                 课题背景（注入 LLM 提示词）
  notes/<citekey>.md         ★真源：元数据 (YAML frontmatter) + 精读笔记正文
  papers/<citekey>.<ext>     ★真源：主文件（pdf）
  papers/<citekey>_SI.<ext>  ★真源：补充材料；多个时 _SI2、_SI3 …
  text/<citekey>.txt         全文文字缓存（可由 papers/ 重新抽取，但保留以省时间）
  topics/<名称>.md           主题综述，用 [[citekey]] 引用
  data/performance.csv       结构化性能数据（每行一组测试条件）
  vocab/tags.yaml            标签词表
  vocab/journals.yaml        期刊全名、缩写、别名、是否顶刊
  vocab/characterization.yaml 表征方法规范名与别名
  vocab/discovery.yaml       查新领域定义与分类规则
  inbox/                     待入库文件
  exports/                   导出物（bib、RIS、docx、xlsx、可读版笔记…），可随时删除
  .papertrail/
    index.db                 可重建索引
    state.db                 运行状态（不可重建）
    cache/                   HTTP 缓存
    trash/<时间戳>-<操作>/   回收区
    backups/<时间戳>/        格式迁移前的自动备份
    browser/                 机构登录用的浏览器会话目录
    logs/
    lock                     库级写锁文件
```

规则：

- 一篇文献的身份是 citekey。它的文件集合是：`notes/<ck>.md`、`papers/<ck>.<ext>`、`papers/<ck>_SI*.<ext>`、`text/<ck>.txt`。查找时按这四种确切模式匹配，**禁止** `glob(ck + "*")`（`X` 与 `X-2` 是两篇不同文献）。
- 文本文件一律 UTF-8 无 BOM、LF 换行。
- `library.bib`、`INDEX.md`、`KEYWORDS.md`、`notes-readable/` 在 v1 中不存在于库内，需要时由 `exports` 生成到 `exports/`。
- 扩展名统一小写。

## 2. papertrail.toml

```toml
[library]
format_version = 1
name = "我的文献库"

[llm]
base_url = "https://api.deepseek.com"
model_extract = "deepseek-v4-flash"      # 抽取档
model_summarize = "deepseek-v4-pro"      # 总结档
max_concurrency = 4
timeout_seconds = 120
max_fulltext_chars = 200000

[ingest]
skip_non_journal = true
title_duplicate_threshold = 0.90
si_filename_threshold = 0.82
si_filename_min_chars = 10
si_orphan_auto_threshold = 0.85
si_orphan_report_threshold = 0.55
crossref_title_threshold = 0.90

[note]
language = "zh"
readable_wrap = 60
# 正文小节：id 是程序用的稳定标识，heading 是写进文件的二级标题
sections = [
  { id = "summary",            heading = "三句话总结" },
  { id = "problem_conclusion", heading = "研究问题与核心结论" },
  { id = "method_points",      heading = "方法要点" },
  { id = "key_results",        heading = "关键图表与数据" },
  { id = "relevance",          heading = "与我课题的关联" },
  { id = "caveats",            heading = "质疑与局限" },
  { id = "further_reading",    heading = "值得追的参考文献" },
]

[network]
contact_email = ""            # 可选，用于 Crossref/OpenAlex/Unpaywall 的礼貌池

[acquire]
min_interval_seconds = 20     # 机构下载两次请求的最小间隔
daily_limit = 50
```

API 密钥不在此文件中，存系统凭据库（服务名 `papertrail`，键名 `llm_api_key`）。

## 3. 笔记文件

### 3.1 结构

```
---
<YAML frontmatter>
---

## <小节标题 1>
<正文>

## <小节标题 2>
…
```

- 正文是 Markdown。按 `papertrail.toml` 的 `[note].sections` 顺序排列二级标题。读取时未知的二级标题原样保留在末尾（用户手写的额外小节不能丢）。
- 小节内容允许为空字符串。

### 3.2 frontmatter 字段（固定顺序）

| 键 | 类型 | 必填 | 约束 | 旧系统对应 |
|---|---|---|---|---|
| `citekey` | str | 是 | 见第 4 节；必须等于文件名 | citekey |
| `title` | str | 是 | 非空，单行 | title |
| `authors` | list[str] | 是 | "名 姓"全名，原文顺序；未知时 `[]` | authors_full（旧 `authors` 显示串丢弃，改为派生） |
| `year` | int \| null | 是 | 1800–2100；未知为 null | year（旧 `unknown` → null） |
| `journal` | str \| null | 是 | 期刊全名 | journal（旧 `unknown` → null） |
| `doi` | str \| null | 是 | 小写、不带 `https://doi.org/` 前缀；无则 null | doi（旧 `N/A` 等占位值 → null） |
| `volume` | str \| null | 是 | | 新增 |
| `issue` | str \| null | 是 | | 新增 |
| `pages` | str \| null | 是 | 页码范围或文章号 | 新增 |
| `entry_type` | str | 是 | `article`（默认）\| `review` \| `preprint` \| `book` \| `thesis` \| `other`，用于导出 | 新增，迁移时一律 `article` |
| `type` | str \| null | 是 | `computational` \| `experimental` \| `combined` \| `review` | 类型：计算 / 实验 / 计算+实验（含 实验+计算）/ 综述 |
| `tags` | list[str] | 是 | 入库时 1–4 个；取值应在 `vocab/tags.yaml` 中 | tags |
| `keywords` | list[str] | 是 | 入库时 5–10 个，可为 `[]` | keywords |
| `methods` | str | 是 | 可为空串 | 方法关键词 |
| `characterization` | list[str] | 是 | 规范名，可带前缀 `in situ` / `operando` / `ex situ` + 空格 | 表征方法（去掉 `unmapped:` 的项） |
| `characterization_unmapped` | list[str] | 是 | 未能归一化的原文写法 | 表征方法里带 `unmapped:` 前缀的项（去前缀） |
| `system` | str | 是 | 可为空串 | 体系 |
| `status` | str | 是 | `unread` \| `skimmed` \| `read` | status |
| `rating` | int \| null | 是 | 1–5 | rating（`★` 的个数） |
| `related` | list[str] | 是 | citekey 列表 | related |
| `si_files` | list[str] | 是 | `papers/` 下的文件名 | si_files |
| `added` | datetime | 是 | ISO 8601 本地时间，秒精度，如 `2026-07-18T14:03:22` | added（日期）+ 旧文件 mtime 的时间部分 |

- 模型禁止未知键（`extra="forbid"`）。读到未知键时报校验错误而不是静默丢弃。
- `tags` 1–4、`keywords` 5–10 是**入库时**对 LLM 输出的要求，不是文件校验规则；文件校验只要求类型正确。
- 界面显示的中文标签（"类型：计算+实验"）由前端按 `type` 的值翻译，文件里只存英文代码。

### 3.3 YAML 输出规则（确定性）

- 键顺序按上表。
- 字符串：凡含 `: `、`#`、首尾空格、以特殊字符开头、或会被解析成非字符串（`true`、`null`、数字、日期样式）的，一律双引号；其余不加引号。实现方式：自定义 Dumper，写完后必须能被 `yaml.safe_load` 读回完全相同的值（测试强制）。
- 列表用行内流式 `[a, b, c]`，元素按同样规则加引号；空列表 `[]`。不折行（`width` 设为极大）。
- null 写作空值（`rating:`），`added` 写不带引号的 ISO 字符串并在读取时按 datetime 解析。
- `---` 与正文之间空一行；文件以单个换行结尾。

示例：

```yaml
---
citekey: 2024-SciAdv-Water-Resistant-OPD-Vital-Sign
title: "A water-resistant, ultrathin, conformable organic photodetector for vital sign monitoring"
authors: [Baocai Du, Sixing Xiong, Takao Someya]
year: 2024
journal: Science Advances
doi: 10.1126/sciadv.adp2679
volume:
issue:
pages:
entry_type: article
type: experimental
tags: [半导体光电, 高分子]
keywords: [water-resistant, organic photodetector, ultrathin]
methods: 器件制备；TOF-SIMS；AFM；光电性能测试
characterization: [TOF-SIMS, AFM]
characterization_unmapped: [J-V measurements, EQE, detectivity, SCLC]
system: "PBDTTT-OFT:N2200:SEBS ultrathin organic photodetector"
status: skimmed
rating:
related: []
si_files: []
added: 2026-07-18T14:03:22
---
```

## 4. citekey

- 形式：`<年份>-<期刊缩写>-<提炼标题>[-<n>]`。
- 校验正则：`^(\d{4}|unknown)-[A-Za-z0-9]+-[A-Za-z0-9]+(-[A-Za-z0-9]+)*$`。
- 年份未知写 `unknown`；期刊未知时缩写写 `unknown`。
- 期刊缩写取自 `vocab/journals.yaml`；表里没有时由 LLM 建议，并作为待确认项写入词表（标 `unreviewed: true`）。同一期刊只能有一个缩写。
- 提炼标题：3–6 个英文词，连字符连接；元素符号与领域缩写保持原大小写，其余首字母大写。
- 撞名时追加 `-2`、`-3`…
- citekey 一经生成即为稳定标识。改名只能通过 `maintenance.rename`，它负责同步全部文件、`related`、`topics/` 里的 `[[…]]`、`performance.csv` 和 `state.db`。

## 5. 词表文件

```yaml
# vocab/tags.yaml
tags:
  - name: OER
    aliases: []            # 归一化时别名 → name
    description: ""
    unreviewed: false      # 自动收编、尚未被用户确认的标 true
```

```yaml
# vocab/journals.yaml
journals:
  - name: Journal of the American Chemical Society
    abbr: JACS
    aliases: [J. Am. Chem. Soc., JACS]
    top: true              # "top journals" 名单
    unreviewed: false
```

```yaml
# vocab/characterization.yaml
prefixes: ["in situ", "operando", "ex situ"]
methods:
  - name: XRD
    aliases: [PXRD, powder XRD, GIXRD, SXRD]
    parent:                # 可选的上位技术
```

```yaml
# vocab/discovery.yaml
fields:
  - name: PEM催化剂
    queries: ["iridium oxygen evolution", "ruthenium oxide PEM water electrolysis", "acidic OER catalyst"]
    journals: top          # top = journals.yaml 里 top: true 的全部；或显式列表
    categories:            # 按标题正则粗分类，先命中先得；都不中为 Unclear
      - { name: Ir-based, pattern: "(?i)\\b(iridium|IrO|Ir-)" }
```

期刊名比较做归一化（忽略大小写、首尾空格、开头的 The），不再要求与笔记里逐字一致。

## 6. data/performance.csv

列（与旧系统相同，顺序固定）：

`citekey,row_id,test_type,reaction,electrolyte,temperature_C,catalyst_loading_mg_cm2,current_density_ref_mA_cm2,overpotential_mV,cell_voltage_V,tafel_slope_mV_dec,stability_duration_h,degradation_rate,other_metrics,source_location`

- `row_id` = `<citekey>#<n>`。`test_type` ∈ `half-cell` | `MEA` | `full-cell` | `unknown`。
- 每个 `citekey` 必须存在于 `notes/`（doctor 检查）。

## 7. index.db（可重建）

```sql
meta(key TEXT PRIMARY KEY, value TEXT)                 -- schema_version, built_at
papers(citekey TEXT PRIMARY KEY, title, year INT, journal, journal_norm, doi,
       volume, issue, pages, entry_type, type, methods, system, status, rating INT,
       added TEXT, has_pdf INT, si_count INT, is_top_journal INT,
       note_size INT, note_mtime REAL, note_hash TEXT)
paper_authors(citekey, position INT, name)
paper_tags(citekey, tag)
paper_keywords(citekey, keyword)
paper_characterization(citekey, method, mapped INT)
paper_related(citekey, related_citekey)
sections(citekey, section_id, content)                 -- 正文各节
notes_fts USING fts5(citekey UNINDEXED, title, authors, keywords, body)
fulltext_fts USING fts5(citekey UNINDEXED, text)       -- 来自 text/，可在配置中关闭
performance(row_id TEXT PRIMARY KEY, citekey, …同 CSV 列…)
```

- 同步：遍历 `notes/`，size + mtime 未变的跳过，变了的比对内容哈希后重新解析；库里已不存在的文件对应行删除。
- 解析失败的笔记不进索引，记入 `index_errors(citekey, error)`，由 doctor 报告。
- 用户直接用编辑器改笔记是受支持的用法：下次打开库或调用 `index.sync()` 时生效。

## 8. state.db（不可重建，迁移与备份对象）

```sql
meta(key, value)                                        -- schema_version
jobs(id TEXT PRIMARY KEY, kind, params_json, status,    -- queued|running|succeeded|failed|cancelled|interrupted
     progress_done INT, progress_total INT, message,
     result_json, error_json, created_at, started_at, finished_at)
job_logs(job_id, seq INT, at, text)
review_items(id TEXT PRIMARY KEY, kind,                 -- duplicate|doi_unverified|si_pairing|metadata_missing|non_journal
             job_id, payload_json, status,              -- open|resolved|dismissed
             decision_json, decided_by, created_at, decided_at)
ingest_ledger(sha256 TEXT PRIMARY KEY, original_name, outcome,  -- ingested|duplicate|skipped|error|pending_review
              citekey, detail, at)
scan_watermarks(field TEXT PRIMARY KEY, last_scanned TEXT, history_json)
wanted(id TEXT PRIMARY KEY, doi, title, journal, year, category, source_field,
       status,                                          -- wanted|downloaded|ingested|failed|dismissed
       detail, created_at, updated_at)                  -- 查新产出的"待下载"清单
llm_usage(at, job_id, tier, model, prompt_tokens INT, completion_tokens INT)
```

## 9. Word 文档内的引用（v1 约定，细节见阶段 10 规格）

- 每处引用是一个富文本内容控件，`Tag = "papertrail:cite:<citekey>[;<citekey>…]"`，显示文本由当前样式渲染。
- 参考文献表是一个内容控件，`Tag = "papertrail:bibliography"`。
- 当前样式名存在文档自定义属性 `PaperTrailStyle`。
- 文档旁不再有外置状态文件。

## 10. 格式演进

- 任何改变本文件第 1–6、8 节的改动都要：递增 `format_version`、在 `core/library.py` 的迁移表里登记一个 `migrate_vN_to_vN+1(library)` 函数、补一个从旧版样例库升级的测试。
- 新增可选的 frontmatter 字段也算格式改动（因为禁止未知键）。
