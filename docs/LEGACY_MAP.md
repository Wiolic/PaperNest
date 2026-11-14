# 旧系统对照表

本文档是 PaperNest 重写的"旧功能 → 新模块"对照。旧系统位于 `D:\Desktop\Reference\PaperTrail`（严格只读）。内容来自对旧系统 `AGENTS.md`、`CLAUDE.md`、`scripts/` 下全部 `.py`/`.sh`（含 `scripts/ui/app.py`）的逐文件阅读，以及对旧库数据的少量只读核对（文件计数、grep）。

约定：
- 引用格式为 `脚本名:函数名`；"待核实"表示读代码后仍不能确定、实现时需要实测。
- "抽取档" = `deepseek-v4-flash`（纯结构化抽取），"总结档" = `deepseek-v4-pro`（读者会看的内容或判断）。新系统模型名一律走配置，不在代码里写死。
- 新模块列只使用任务约定的模块名。
- 旧库实测快照（只读核对，用于迁移与回归用例）：`notes/` 406 篇；其中 401 篇 citekey 以数字开头，5 篇不是（例如 `unknown-AdvFunctMater-...`、`unknown-unknown-...`）；121 篇笔记含 `unmapped:` 前缀；`INDEX.md` 头部仍写"共 0 篇"；`papers/` 中 SI 附件 28 个（19 个 pdf、9 个 docx）；标题含 `: ` 的笔记 48 篇（只统计 title 字段；全字段口径"406 篇里 71 篇"出自任务说明，待迁移时实测）。

---

## 1. 脚本对照

### 1.1 逐脚本对照

| 旧脚本 | 做什么 | 新模块 | 处理方式 | 必须保留的行为细节 |
|---|---|---|---|---|
| `batch_ingest.py`（828 行） | 扫源目录 PDF，按文件夹配 SI，调 LLM 抽元数据并写七节笔记，Crossref 覆盖元数据，三层查重，生成 citekey，写 papers/notes/notes-readable/extracted-text/bib/INDEX 六处，断点续跑 | `services.ingest`、`services.dedupe`、`services.si_pairing`、`core.citekey`、`core.textsim`、`core.note_io`、`adapters.pdf_text`、`adapters.crossref`、`adapters.llm`、`services.exports` | 重写并拆分；无人值守批模式保留为 ingest 的 auto 模式，存疑项进 review 而不是只打印 | `--limit` 默认 15；`--until-done` 连续跑批；模型默认总结档，`temperature=0`、JSON 模式、`reasoning_effort="low"`；PDF 全文上限 `max_chars=200000`；strip 后文字少于 50 字符判扫描件；`is_journal_article=false` 默认跳过（`--no-skip-non-journal` 关闭）；`EXCLUDED_FOLDER_NAMES={"电镜资料"}`；排除落在 papers/notes/notes-readable/extracted-text 内的源文件；Crossref 命中后覆盖 doi/title/journal/year/authors_full；status 固定 `skimmed`；`READABLE_WIDTH=60`；每批结束汇总新建/跳过重复/非期刊/出错；SI 目标名 `<citekey>_SI<小写扩展名>` |
| `ingest_from_meta.py` | 把 `ds.py pdf-meta` 的 JSON 直接落盘成六处文件（不做查重/DOI 核实/SI 配对） | `services.ingest` | 并入 ingest 的"落盘"步骤；不再有独立脚本（抽取结果缓存在 state，以 sha256 为 key） | citekey 已存在则拒绝；传入的 citekey 和 SI 就是最终决定；落盘顺序 PDF→SI→bib→笔记→全文缓存→INDEX（新系统改为原子事务，见第 5 节）；SI 复制并改名 `<citekey>_SI<扩展名>` |
| `ds.py` | DeepSeek 调用原语：`chat`/`json`/`pdf-meta` 三个子命令 | `adapters.llm`、`interfaces.cli` | 重写为 `adapters.llm`（两档模型、重试、限流、输出校验）；CLI 只保留调试命令 | 默认模型 flash，`pdf-meta` 默认 pro；`temperature` 默认 0；`reasoning_effort` 默认 low（据文档 low/medium 会映射为 high，仅 high/max 真生效）；`json` 模式返回前 `json.loads` 校验；Windows 下 stdout 重配 UTF-8；缺 key 给明确报错；`pdf-meta` 读不到文字（少于 50 字符）报"可能是扫描件" |
| `backfill_fields.py` | 一次性：给早期笔记补 `authors_full`、`表征方法`，同步 bib author 与可读版 | `papernest.migrate` | 仅迁移时用一次 | 只读 `text[:12000]`；抽取档；客户端 `timeout=30`、`max_retries=1`；已有字段不覆盖（`already_has_field` 用 `^field:`）；bib author 用 `authors_full` 以 ` and ` 连接。迁移工具应检测缺失这两个字段的旧笔记并报告 |
| `map_characterization.py` | 把 `表征方法` 自由文本映射到 `vocab/characterization.yaml` 规范写法 | `services.maintenance`、`core.vocab` | 并入 maintenance（"表征方法归一化"），词表归 `core.vocab` | 纯词表查找，不调 LLM；大小写不敏感匹配规范名和 aliases；先剥离前缀 `in situ`/`operando`/`ex situ`（后接空格或连字符），查表后把前缀原样拼回，绝不合并 in situ 与 operando；词表层级 `parent` 仅供查阅，不做上位归并（EXAFS 不并入 XAS）；`--dry-run`；未映射项汇总到 `vocab/unmapped_characterization.md`（新系统改进 review/报告，不写进 frontmatter） |
| `match_orphan_si.py` | 给跨文件夹配不上的 SI：读首页文字，LLM 识别其所属主论文标题，与库内标题相似度匹配后绑定 | `services.si_pairing`、`services.review` | 重写；≥0.85 自动绑定，0.55~0.85 进 review | `AUTO_APPLY_THRESHOLD=0.85`、`REVIEW_THRESHOLD=0.55`；只读首页（`max_pages=1,max_chars=3000`）；抽取档；弱信号配对（同文件夹仅 2 文件）也纳入待匹配；已绑定则跳过；绑定动作 = 复制为 `<citekey>_SI.<ext>`、更新 `si_files`、更新 SI 标记；默认预览，`--apply` 才写；主论文未入库时配不上属预期 |
| `reconcile_state.py` | 用本地正则从 PDF 前 3 页抓 DOI，与 bib 比对，把已处理的源文件在 state 里标记为重复，避免白花 LLM 调用 | `services.ingest`、`core.state` | 不再需要，因为入库台账以文件 sha256 为 key，且入库前会先用本地 DOI 预查重；DOI 正则并入 `adapters.pdf_text` | DOI 正则 `\b10\.\d{4,9}/[^\s"'<>()]+`；只读前 3 页、8000 字符；去掉尾部 `.,;:`；转小写再比对；零 LLM 成本 |
| `remove_citekeys.py` | 按 citekey 清单彻底移除：papers(含 SI)、notes、readable、全文缓存、bib 条目、INDEX 行；state 记录改 `excluded_by_user` | `services.maintenance` | 重写；删除一律进回收区 | state 里保留"用户已排除"痕迹，防止以后重跑同一来源时被当新文件重新入库；默认预览，`--apply` 才执行；执行后同步 INDEX 计数；批量删除先列清单给用户确认（红线）。旧实现用前缀 glob，见第 5 节 |
| `rename_citekeys.py` | 一次性：旧格式 citekey（`<姓><年份>_<短标签>`）迁移到新格式，用 LLM 生成期刊简称和提炼标题 | `papernest.migrate`、`services.maintenance` | 迁移部分仅迁移时用一次；"改名"机制并入 maintenance.rename | 旧格式判定 = 不匹配 `^[0-9]{4}-`；抽取档，输入只有标题+期刊；改名涉及 papers(含 SI)/notes/readable/bib/INDEX/state；`str.replace(old,new,1)` 改 SI 名；glob 不能对 citekey 做 `re.escape`（`-` 会被转义导致静默漏掉 SI） |
| `rename_journal_abbr.py` | 批量把 citekey 里某个期刊简称改成另一个（如 ACIE→AngewChemIntEd） | `services.maintenance`、`core.vocab` | 并入 maintenance.rename；期刊缩写改为 `core.vocab` 的映射表 | 只匹配 `^(\d{4}-)<简称>-` 位置，不误改标题片段；默认预览，`--apply` 才写；改名后需重新同步可读版；全库笔记里的旧 citekey 引用（related、`[[...]]`）要一并替换 |
| `resolve_duplicate.py` | 合并两个确认重复的 citekey：较优字段并入 winner，删除 loser 五处记录 | `services.maintenance`、`services.dedupe` | 重写为 maintenance.merge；删除进回收区 | 合并规则：winner 的 doi 缺失且 loser 有效则取 loser；winner keywords 为空且 loser 非空则取 loser；si_files 取并集；其余字段保留 winner；默认预览，`--apply` 才执行；判重不是它的职责；单对可直接处理，5 组以上先列清单 |
| `render_readable_notes.py` | 从 `notes/` 全量重新生成 `notes-readable/` | `services.exports` | 并入 exports（可读笔记按需导出），不再有独立真源之外的第二份目录 | 折行规则见第 3 节（60 字符、frontmatter 和标题行不折）；`newline="\n"` 写出 |
| `build_keyword_index.sh` | 汇总 tags/keywords/表征方法的出现次数，生成 `KEYWORDS.md` | `services.exports`、`core.index` | 重写为 exports 导出物，数据来自 SQLite 索引 | 三节：受控标签、自由关键词、表征方法；条目格式 `- **词** (次数) — citekey1, citekey2`，按次数降序；头部写更新日期和三类词数；空节写"（暂无）"；LLM 写笔记前读这张表复用已有词 |
| `check_library.sh` | 体检：papers/notes/bib 三方对账、readable 与 extracted-text 同步、重复 DOI、SI 绑定核对、全库标题查重 | `services.doctor` | 重写；Git Bash 依赖消失 | 检查项见第 3 节 R29；默认每类问题只列前 5 条（`TRUNCATE_AT=5`），`--verbose` 看全部；发现问题退出码 1；主 PDF 列表排除 `_SI.pdf`；重复 DOI 比对排除缺失占位值；inbox 有 PDF 时提示数量（仅提示，不算问题） |
| `find_duplicate_titles.py` | 全库标题相似度查重 | `services.dedupe`、`services.doctor` | 并入 dedupe，被 doctor 调用 | 阈值默认 0.90（`--threshold`）；`difflib.SequenceMatcher` 对小写标题；两两比较 O(n²)；有重复返回 1；只报告，不删除（红线） |
| `build_topic_digest.py` | 主题综述第一步：按 tags/标题正则/关键词正则筛笔记，抽方法要点摘录，标题查重，可选调 LLM 起草初稿 | `services.topics` | 重写 | tags 任一命中（小写比较）；`--title-regex` 匹配 title；`--keyword-regex` 匹配 title+体系+keywords 拼接；三者至少给一个；按 `(year, citekey)` 排序；组内标题相似度 ≥0.90 提示疑似重复；小节为空或以 `<!--` 开头视为空；`--draft` 用总结档，输出 `<out>.draft.md`；初稿必须核对每个 `[[citekey]]` 真实存在 |
| `md_to_docx.py` | 把综述 Markdown 子集转成 docx | `services.topics` | 并入 topics（docx 是必做的最后一步） | 支持 `#`~`####` 标题、段落、`**粗体**`、`[[citekey]]`（斜体 Consolas 9.5pt，颜色 `445588`）、表格（样式 `Light Grid Accent 1`，首行加粗，跳过分隔行）、`-`/`*` 列表、`---` 分隔线（下边框模拟）、`>` 引用块（缩进 18pt、斜体、灰色）；正文字体微软雅黑 10.5pt（含 eastAsia）；不支持嵌套列表、脚注、图片、代码块；生成后用 python-docx 读回段落数/表格数/citekey run 斜体做结构校验 |
| `find_citations.py` | "引文献"：单句或整段，按关键词/标签/顶刊筛候选，LLM 判 support/contradict/unclear | `services.citations` | 重写 | 单句模式必须给 `--keyword-regex`；候选检索字段 = title+体系+keywords+关键图表与数据；tags 任一命中；`--top-journals` 只留白名单期刊；整段模式先拆论点（总结档）再逐条检索；判断用总结档；输出必须带论文标题，格式 `citekey — 《标题》(期刊, 年份) [判断]: 理由`；跳过的论点标注"无需引用"及原因，不静默丢弃；库内判断偏保守时人工可 override |
| `export_for_endnote.py` | 把指定 citekey 导出成 RIS（默认）或 BibTeX | `services.exports` | 并入 exports | RIS 字段 `TY  - JOUR`、`AU  - 姓, 名`、`TI`、`JO`、`PY`、`DO`、`UR  - https://doi.org/...`、`N1  - citekey: ...`、`ER  -`；DOI 为 N/A/NA/UNKNOWN 时不写 DO/UR；条目间空行；找不到的 citekey 警告并跳过，一个都没有则退出；不附带 PDF |
| `export_referable_folder.py` | 按 tags/期刊/标题正则筛选，把 PDF 和可读笔记复制到独立文件夹 | `services.exports` | 并入 exports（导出文件夹） | `--top-journals` 与 `--journals` 二选一；至少给一个筛选条件否则拒绝（防止导出全库）；可重复运行覆盖同名文件；只复制不改源文件；缺失文件列警告 |
| `extract_performance.py` | 从全文缓存批量抽取带条件的性能数据行 | `services.performance` | 重写 | 每行 = 一组测试条件；`row_id = <citekey>#<序号>`；15 列固定（citekey、row_id、test_type、reaction、electrolyte、temperature_C、catalyst_loading_mg_cm2、current_density_ref_mA_cm2、overpotential_mV、cell_voltage_V、tafel_slope_mV_dec、stability_duration_h、degradation_rate、other_metrics、source_location）；`test_type` 受控词表 `half-cell`/`MEA`/`full-cell`/`unknown`，`device` 停用并入 `MEA`；抽取档；`--limit` 默认 20；`--force` 先删旧行再重抽；单篇 `--citekey` 强制重跑且不记 state；读 CSV 用 `errors="replace"` |
| `regenerate_notes.py` | 用全文缓存重新调 LLM，重写正文七节、keywords、类型、方法关键词、表征方法、体系 | `services.regenerate` | 重写 | 只覆盖上述字段；绝不覆盖 citekey/title/authors/authors_full/year/journal/doi/tags/status/rating/related/si_files/added；默认跳过 `status: read`（`--include-read` 才重写）；总结档；`--limit` 默认 20；断点续跑；`--citekeys-file` 限定子集；跑完需同步可读导出 |
| `scan_new_papers.py` | "扩充/查新"核验步：候选 DOI 查 Crossref、只有标题的反查、乱文字交 LLM；对 bib 查重；关键词粗分类；导出 xlsx 和 summary | `services.discovery`、`adapters.crossref`、`adapters.openalex`、`services.exports` | 重写；候选来源改为 OpenAlex API，Crossref 仅作核验 | 候选三种输入（DOI / 仅标题 / 乱文字）；标题反查跳过 `type=component`、相似度 ≥0.90；去重 = DOI 命中，或标题相似度 ≥0.90；status 取 `new`/`already_in_library`；分类取 Ir-based/Ru-based/Ir-Ru-mixed/Non-PGM/Unclear（领域专属，进 `core.vocab` 配置）；xlsx 列 Title/Authors/Journal/Year/DOI/Link/Status/Category/Note；同时输出 `.summary.txt`，只列 `status=new` 并按分类分组，供汇报时只读它 |
| `scan_state.py` | 记录每个"领域"上次扫描到哪天、覆盖哪些期刊 | `core.state` | 并入 state（扫描水位） | 结构 `领域 → {last_scanned, history:[{date, journals, note}]}`；无记录等于第一次，按"扩充"（近 5 年全量）处理；`record`/`show`/`list` 三个动作；日期默认今天 |
| `parse_search_results.py` | 把 WebSearch 原始文字交 LLM 抽成候选 JSON | 无 | 不再需要，因为查新改用 OpenAlex API，返回的就是结构化数据，不必从网页噪声里抽候选 | 仅当保留"贴文字导入候选"的后备入口时，才需要它的去重规则（同一论文多次出现只输出一次、非论文内容不输出、不确定字段留 null、不猜 DOI） |
| `word_insert_citation.py` | 通过 pywin32 连到已打开的 Word，在光标处插入编号引用并维护 References | `services.word` | 重写（仍仅 Windows+Word） | 不自己启动 Word、不开文件；多个文档必须 `--doc`；四种样式 numbered/nature/wiley/gbt7714（近似风格）；多 citekey 合并为 `[n1,n2]`；同 citekey 重复插入复用编号；`<文档名>.citemap.json`（v2：`{style, map}`，兼容旧扁平格式）；`--rebuild` 两阶段替换，见第 3 节 R11；不自动保存；Word 段落分隔符是 `\r` |
| `word_auto_cite.py` | 扫描已打开文档全文，拆论点、检索候选、判断方向，对 support 句尾自动插引用 | `services.word`、`services.citations` | 重写 | 默认预览，`--apply` 才写；References 小节之前为正文；每句只自动插第一条 support；定位靠 Word Find 精确匹配，定位失败列出供手动补插；总结档用于拆句和判断；`--top-journals`、`--tags`、`--style` |
| `ui/app.py`（982 行） | Streamlit 本地面板：总览/文献库/编辑资料/体检/引文献/主题综述/扩充查新/Word/命令 | `interfaces.web`、`interfaces.api` | 重写，见第 2 节 | 见第 2 节 |
| `ui/run_hidden.vbs`、`ui/watchdog.bat`、`PaperTrail Launcher.bat` | 隐藏窗口启动 Streamlit；守护循环；双击启动器 | `interfaces.cli`、`interfaces.web` | 不再需要，因为 PaperNest 是正式打包的软件，由 CLI 子命令/桌面入口启动 | 仅一点值得保留：启动不留常驻命令行窗口；旧端口不一致（CLAUDE.md 写 8501，vbs 和 watchdog 用 8502） |
| 数据文件 `top_journals.txt`、`tag_vocab.txt`、`research_profile.md`、`vocab/characterization.yaml` | 顶刊白名单、标签受控词表、课题背景、表征方法词表 | `core.vocab`、`core.library` | 并入 vocab（词表）和库设置（课题背景）；`migrate` 导入 | `top_journals.txt` 每行一个期刊全名，必须与笔记 `journal` 字段逐字一致（旧实现不做模糊匹配，新系统用期刊映射表归一后再比对）；不含 Nature Communications/Nature Reviews 系列/Nature Protocols；`tag_vocab.txt` 缺失或为空则回退内置默认 29 个标签；`research_profile.md` 缺失时 prompt 要如实写"未配置课题背景"，不得编造 |
| 状态文件 `.ingest_state.json`、`.performance_state.json`、`.regenerate_state.json`、`.scan_state.json`（`.local_config.json` 仅记名称，未读取） | 各脚本各自的断点/水位/本机配置 | `core.state`、`adapters.secrets` | 各状态并入 state（统一表、sha256 或 citekey 为 key）；明文密钥文件不再需要，密钥进系统凭据库 | `.ingest_state.json` 的 key 是源文件绝对路径（旧缺陷）；value 含 `status`（done/skipped_duplicate/skipped_non_journal/error/excluded_by_user）、`citekey`、`si`；迁移时只能导入"已入库"相关事实，不能导入路径 key |
| 临时文件 `ir_pemwe_subset.txt`（50 行）、`ircox_irtaox_relevant.txt`（22 行）、`_dryrun1.txt`（107 行，UTF-16 编码的 dry-run 输出） | 一次性 citekey 清单与调试输出 | 无 | 不再需要（前两个是 citekey 清单，可由 exports 的筛选重新生成；第三个是调试输出） | 内容未逐行阅读，按用途判断，待核实 |
| `schema/note-frontmatter.schema.json`、`templates/note-template.md` | frontmatter JSON Schema 与笔记模板 | `core.models`、`core.note_io` | 重写为严格模型 | Schema 要点：citekey 模式 `^[0-9]{4}-[A-Za-z0-9]+-[A-Za-z0-9-]+$`；year 1900~2100；`类型` 枚举 `计算/实验/计算+实验/综述`；`status` 枚举 `unread/skimmed/read`；rating 模式 `^★{1,5}$`；si_files 模式 `...\_SI\.(pdf|docx|doc)$`（只认小写扩展名）；`additionalProperties:false`；必填 13 个字段；`keywords` 在 schema 里非必填但 AGENTS 要求 5~10 个；字段名含中文（类型/方法关键词/表征方法/体系）由 DATA_MODEL 决定是否改名，`migrate` 负责映射 |

### 1.2 旧系统里不是脚本、但属于功能的对话流程（CLAUDE.md "常用短指令"）

| 旧流程 | 新模块 | 处理方式 | 必须保留的行为细节 |
|---|---|---|---|
| "入库"（路线 C：ds.py pdf-meta + 人工审核 + ingest_from_meta） | `services.ingest`、`services.dedupe`、`services.si_pairing`、`services.review` | 全流程服务化；需要人判断的三个环节（查重存疑、DOI 存疑、SI 配对存疑）进 review 审核队列 | 步骤：抽取→查重→DOI 核实→SI 配对→落盘；成功入库的源文件删除，确认重复的也直接删（2026-07-20 起），只有存疑项保留；`inbox/.meta_cache/<PDF名>.json` 缓存抽取结果，续跑复用，成功落盘后连同源 PDF 一并清理（新系统改为 sha256 为 key 存 state，删除进回收区） |
| "体检" | `services.doctor` | 同上 | 报告孤儿 PDF、缺笔记、缺 bib、重复 DOI；发现关键词近义词泛滥时提示合并 |
| "top journals" | `core.vocab` | 名单作为词表 | 以 `top_journals.txt` 为唯一来源；边界（不含 NatCommun）是维护者默认判断，用户没有明确确认，实现时做成可配置 |
| "把 XX 主题 top journals 整理到 YY 文件夹" | `services.exports` | 并入导出文件夹 | 同 `export_referable_folder.py` |
| "扩充"/"查新" | `services.discovery`、`core.state` | 查新用 OpenAlex | 扩充 = 近 5 年全量；查新 = 只搜上次水位之后；同一领域按子类分别检索；检索不能锚定单一元素词（见 R24）；汇报只读 summary |
| "引文献" | `services.citations` | 同上 | 同 `find_citations.py` |
| "导出成 EndNote 能导入的格式" | `services.exports` | 同上 | 同 `export_for_endnote.py` |
| "在 Word 光标处插入引用"、"一键添加建议的文献" | `services.word` | 同上 | 同上两个 word 脚本 |
| "打开操作面板" | `interfaces.web` | 同上 | 见第 2 节 |
| "把系统挂 GitHub"/"打包上传" | 不属于新系统运行时功能 | 不再需要（2.0 本身就是正式仓库）；若要发布开源骨架，由发布流程处理 | 旧规则：只打包骨架（AGENTS/CLAUDE/scripts/templates/schema/prompts 等），不打包 papers/notes/extracted-text/library.bib 等实际文献数据；领域专属内容标 `[领域定制]` |
| 路线 A（Codex CLI + DeepSeek）与 `prompts/deepseek-使用指南.md` | `interfaces.mcp`、`interfaces.cli` | 不再需要，因为内容生产由 ingest 服务直接完成；外部 Agent 通过 MCP 调用服务 | 旧红线（绝不修改 EndNote 库及主题文件夹，只复制不移动）要在 ingest 的"外部来源只读"规则中保留 |

---

## 2. 界面功能对照

旧面板是单页 Streamlit，九个标签页加顶部 API Key 区。前端页面名为暂定名，API 端点按所属服务列出（具体路由由 ARCHITECTURE/specs 定）。

| 功能 | 新系统对应 | 备注 |
|---|---|---|
| 顶部 DeepSeek API Key 输入、"保存到本机"、"忘记" | `adapters.secrets`（系统凭据库）；前端 Settings 页 | 旧实现明文写 `scripts/.local_config.json`，并通过环境变量注入子进程。新系统不得明文落盘，进程内调用 `adapters.llm`，不再需要子进程注入 |
| 总览：库内文献数、inbox 待处理数、关键词索引条目数 | `core.index` 统计；Overview 页 | 旧关键词条目数是数 `KEYWORDS.md` 里 `\n- ` 的估算，新系统直接查索引得精确值 |
| 总览：拖拽/多选上传 PDF 到 inbox | `services.ingest`（接收上传）；Overview 页 | 旧实现直接用上传文件名写入 inbox，同名静默覆盖；新系统需清洗文件名、不覆盖、以 sha256 识别重复上传 |
| 总览："入库"按钮（对 inbox 跑 `batch_ingest.py --source inbox --until-done`，超时 1800 秒） | `services.ingest` + `services.jobs`；Overview 页 | 旧面板这条路径绕过审核（无人值守，不核实查重/DOI/SI），新系统改为自动处理 + 存疑进 review；任务进度、日志、取消由 jobs 提供 |
| 总览：入库后按 state 自动删除 inbox 里 done/skipped_duplicate 的 PDF | `services.ingest`（回收区） | 旧实现兼容三种路径写法的 state key，是路径 key 缺陷的补丁；新系统以 sha256 判定 |
| 总览："清理 inbox"（无确认，直接删文件和子目录，含 `.meta_cache`） | `services.maintenance`（回收区）；Overview 页 | 必须二次确认并进回收区，不得 `rmtree` |
| 总览："刷新库列表"（改缓存键强制重扫 notes） | `core.index`（可重建索引）；Overview 页 | 新系统索引随写入增量更新，保留"重建索引"入口即可 |
| 总览："最近新增" 5 条（按文件 mtime 倒序） | `core.index` 查询；Overview 页 | 旧实现用 mtime 是因为 `added` 只有日期粒度；但重生成/改名会改 mtime 导致"最近新增"错乱，新系统需要可靠的入库时间（待 DATA_MODEL 定） |
| 文献库：标题/关键词子串搜索 | `core.index`（FTS5）；Library 页 | 旧实现只匹配 title 和 keywords 的小写子串；新系统可扩展到全字段与正文 |
| 文献库：按 tags 多选筛选（任一命中） | `core.index`；Library 页 | 任一命中语义要保留 |
| 文献库：分页，每页 50 篇；按 mtime 倒序 | `core.index`；Library 页 | `PAGE_SIZE=50`；排序键同上 |
| 卡片：标题、期刊·年份·citekey、tag 小方块、keywords | Library 页组件 | 缺期刊显示"期刊未知"，缺年份显示"年份未知" |
| 卡片："笔记"按钮（右侧阅读窗格）、"PDF"按钮（系统默认阅读器打开） | `interfaces.api`（读笔记、取 PDF）；Library 页 | 旧实现 `os.startfile`，仅 Windows；无 PDF 时按钮禁用并显示"无PDF" |
| 阅读窗格：标题、期刊/年份/作者（优先 authors_full）、可点击 DOI（N/A 不显示）、标签、类型/方法关键词/表征方法/体系、七节正文 | `interfaces.api` + Library 页 | 七节小标题缩小渲染但内容不改 |
| 阅读窗格：点窗格外空白关闭、滑入动画、关闭后停留在当前页、滚动位置保持 | `interfaces.web` | 这些是绕开 Streamlit `rerun` 缺陷的 JS 补丁，新前端用路由与组件状态天然解决，不继承实现，但"不因操作丢失当前页和滚动位置"这个目标保留 |
| 编辑资料：课题说明（`research_profile.md`） | `core.library`（库设置）；Settings 页 | 保存后下次入库生效；留空则笔记"与我课题的关联"如实写"未配置课题背景" |
| 编辑资料：Top journals 名单编辑 | `core.vocab`；Settings 页 | 旧实现按文本原样保存 |
| 编辑资料：标签受控词表编辑 | `core.vocab`；Settings 页 | 旧行为：LLM 在词表都配不上时自行新增 1 个标签，不会回写词表；新系统让新增标签进入审核/候选，避免词表悄悄分叉 |
| 体检：运行 `check_library.sh`，可勾"显示全部问题（--verbose）" | `services.doctor`；Doctor 页 | 退出码非 0 属正常（发现问题）；旧实现要显式找 Git Bash，避免 PATH 里 WSL 的 bash |
| 引文献：贴一段正文，可选 top journals、标签过滤，调用 `--paragraph --draft`，展示逐句清单 | `services.citations`；Citations 页 | 超时 300 秒；输出文件放临时目录；展示 Markdown |
| 主题综述 ①：主题名、标签、关键词正则、是否 LLM 起草，生成 digest 与草稿 | `services.topics`；Topics 页 | 主题名直接拼进文件名（`topics/_digest_<名>.md`），新系统必须校验为安全 slug；标签与正则至少填一个 |
| 主题综述 ②：编辑框，实时检查 `[[citekey]]` 是否都在库里 | `services.topics` + `core.index`；Topics 页 | 找不到的 citekey 给警告，全部存在给确认提示 |
| 主题综述 ② 保存为 `topics/<名>.md`；③ 转 docx 并提供下载 | `services.topics`、`services.exports`；Topics 页 | docx 导出到 `exports/`；综述定稿后 docx 是必做的最后一步 |
| 扩充/查新：粘贴搜索原始文字 + 目标说明 → LLM 抽候选 → Crossref 核验/去重/分类 → 摘要 + xlsx 下载 | `services.discovery`；Discovery 页 | 新系统候选来自 OpenAlex；"贴文字/贴 DOI 列表导入"作为后备入口；增加领域选择与水位显示（`core.state`） |
| Word：在光标处插入引用（citekeys、文档名片段、样式选择）、"重新编号"（`--rebuild`） | `services.word`；Word 页 | 仅 Windows+已装 Word；超时 60 秒 |
| Word：自动扫描全文并添加引用（预览/写入、top journals、样式） | `services.word`、`services.citations`；Word 页 | 默认预览，勾选才写入；超时 600 秒 |
| 命令页：直接运行任意命令（`shell=True`） | 不继承 | 等价于任意代码执行，正式软件不提供；用 Jobs 页和 CLI 替代 |
| 命令页：自然语言翻译成命令，确认后手动运行 | 不继承 | 同上；如需自然语言入口，通过 `interfaces.mcp` 暴露受限工具，不生成 shell 命令 |
| 全局：子进程调用脚本（默认超时 600 秒，入库 1800 秒） | `services.jobs` | 改为后台任务，带进度、日志、取消、持久状态 |
| 全局：莫兰迪蓝配色（`#5B7C99`、`#7B93AB`、`#C4D1DB`、背景 `#F4F1EC`、卡片 `#E6E9E4`） | `interfaces.web` 主题 | 可选继承，属视觉偏好 |
| 新增（旧面板没有）：审核队列页 | `services.review`；Review 页 | 旧系统靠对话完成查重存疑/DOI 存疑/SI 配对存疑的人工判断 |
| 新增（旧面板没有）：任务页 | `services.jobs`；Jobs 页 | 长任务可见、可取消、可恢复 |

---

## 3. 必须原样继承的规则

编号 R01~R40，凭此在 specs 与测试里引用。

**R01 查重三层逻辑**（`batch_ingest.py:run_one_batch`、`find_title_duplicate`、`existing_dois`、`existing_titles_with_doi`）
1. 层一，DOI：小写后精确比对，缺失占位值不参与比对（见 R05）。
2. 层二，标题：归一化（空白折叠、转小写）后 `difflib.SequenceMatcher` 比相似度，取 ≥0.90 里最高者。命中后：新论文或已有条目任意一方缺 DOI，或两边 DOI 相同，判重复。
3. 层三，标题高度相似但两边 DOI 都有效且不同：放行入库，并发出警告，交人工核实（新系统进 review"DOI 存疑"）。
- 标题查重不能只在"新论文自己没 DOI"时才触发（踩过的坑：同一篇 Science Advances 论文因 DOI 提取不稳定入库 3 次，两次抽到的 DOI 分别是 `eaea4543` 与 `aea4543`）。
- 标题抽取失败的占位值（见 R05）不参与标题查重，否则两篇都填 `unknown` 的不同论文互相误判。
- DOI 可能"张冠李戴"，不得无条件信任已入库的 DOI（踩过的坑：两篇同名同作者的 Single-Atom Nano-Islands 论文，更早入库的那条 DOI 其实是另一篇同期论文的）。处理任何 DOI 冲突，两边 DOI 都要独立用 Crossref 按 DOI 反查核实。
- 另有三处独立的标题查重口径，均为 0.90：全库体检（`find_duplicate_titles.py`，只用小写、不看 DOI）、主题筛选集内部（`build_topic_digest.py:find_near_duplicates`）、查新对 bib 去重（`scan_new_papers.py:is_duplicate`）。疑似重复只报告，不擅自删除（红线）。

**R02 SI 配对规则与标记词表**（`batch_ingest.py:pair_files`、`_is_si_token`、`group_and_pair`；`match_orphan_si.py`）
- 文件名按 `[^a-z0-9]+` 切 token（先转小写）。SI 标记词集合 `SI_MARKERS = {si, esi, esm, sup, supp, suppmat, supporting, supplementary, supplemental}`，另有正则 `mmc\d+`（Elsevier）和 `moesm\d+`（Springer/Nature）。Wiley 惯例形如 `xxx-sup-0001-suppmat`。
- `.docx`/`.doc` 默认进 SI 候选池，不当独立文献；候选扩展名 `{.pdf,.docx,.doc}`。
- 配对只在同一文件夹内做。强配对（自动绑定）：去掉 SI 标记词后的文件名两边都至少 10 字符、非纯数字，且相似度 ≥0.82。
- 弱信号：文件夹里恰好 2 个文件、1 个主文献、1 个剩余 SI，但文件名毫无关联。只报告，不自动绑定（踩过的坑：论文与行政文档因偶然放在同一文件夹被误判）。
- 配不上的 SI 不瞎配，进存疑；跨文件夹的 SI 走内容匹配（R09 阈值 0.85/0.55）。错配比不配更难发现。
- 文件名配对在杂乱下载目录里连踩三个坑：空字符串是任何串的子串；短数字片段（如年份）凑巧出现在无关编号里；短学术文件名相似度虚高。因此长度门槛与 0.82 阈值要保留。
- 命名 `<citekey>_SI<扩展名>`，多个 SI 的扩展名不同时靠扩展名区分，写入 `si_files`。
- 同一来源文件夹只有 2 个文件（EndNote 式规整来源）只算弱信号，不得因此自动绑定。

**R03 citekey 生成与撞名后缀**（`batch_ingest.py:make_citekey`；AGENTS.md citekey 规则）
- 格式 `<年份>-<期刊简称>-<提炼标题>`。期刊简称：去空格、句点和虚词；业界本就全大写的保持全大写（JACS、PNAS、EES）；其余驼峰式截断（ACSNano、NatMater、NatCommun、AdvMater、ChemComm、NanoLett、ACSCatal、ACSEnergyLett、AngewChemIntEd）。每个期刊只能有一种缩写，不用 `ACIE`。
- 提炼标题 3~6 个英文单词，连字符连接。元素符号（Ir、Co、Ru、Ti、Mn、Ni、Pt 等）和领域缩写（OER、HER、PEM、PEMWE、AEM、AEMFC、TEM、SEM、DFT、AIMD、XPS、EELS、STEM、MEA、CCM 等）按规范大小写；其余 Title Case。
- 清洗：简称去掉所有非 `[A-Za-z0-9]`，为空则取 `Journal`；标题空格换连字符，去掉非 `[A-Za-z0-9-]`，合并连续连字符、去首尾连字符，为空则取 `Paper`；不强制转小写。
- 撞名：循环追加 `-2`、`-3`……直到不在已占用集合里。
- citekey 必须在 papers/notes/notes-readable/bib/INDEX 五处完全一致（区分大小写）；新系统五处变为真源加导出物，但引用关系不变。
- 校验正则（schema）：`^[0-9]{4}-[A-Za-z0-9]+-[A-Za-z0-9-]+$`。

**R04 Crossref 采信条件**（`batch_ingest.py:lookup_metadata_via_crossref`；`scan_new_papers.py:crossref_title_lookup`）
- 按标题反查用 `query.bibliographic`，`rows=5`，超时 10 秒。
- 跳过 `type == "component"`（Crossref 把 SI 单独收录，DOI 带 `.s001` 之类后缀，标题与正文一模一样）。
- 返回标题与查询标题（空白折叠、转小写）相似度 ≥0.90 才采信，否则保留 N/A，不瞎猜（Crossref 模糊搜索有过返回完全不相关论文的先例）。
- 查不到或网络出错返回 None，不抛异常打断批次，也不能因此判定论文有问题；上层原样保留 LLM 抽取结果。
- 命中后 Crossref 是 citekey 三要素（年份/期刊/DOI）的权威源：覆盖 doi、title、journal、year、authors_full；LLM 只负责 Crossref 给不了的字段。
- 年份取值顺序（ingest）：`published-print`、`published-online`、`published`、`created`；（discovery）：`published-print`、`published-online`、`published`。两处不一致，需统一（见第 5 节）。
- 带 DOI 的候选直接按 DOI 查询，不经 LLM；标题里的 HTML 标签（`<i>`、`<sub>` 等）要去掉并折叠空白（仅 discovery 做了）。

**R05 缺失值占位集合**
- DOI 缺失占位（`batch_ingest.py:MISSING_DOI_VALUES`，小写比较）：`n/a`、`na`、`unknown`、`none`、`null`、空串、`not available`、`not found`、`not provided`。这些不得参与查重比对。
- 旧代码里还有三份不一致的变体：`resolve_duplicate.py:is_missing_doi`（6 个）、`scan_new_papers.py:is_duplicate`（6 个）、`check_library.sh` 的 grep（8 个）。新系统只保留一份定义。
- 标题缺失占位（`MISSING_TITLE_VALUES`）：`unknown`、`n/a`、`na`、`none`、`null`、空串、`untitled`、`not available`、`not found`。
- 元数据缺失时，prompt 要求填 `"unknown"`（title/authors/year/journal），DOI 填 `"N/A"`，绝不编造 DOI 或年份。
- `extract_performance` 的缺失：数值缺失填 null，`test_type`/`reaction`/`electrolyte` 缺失填 `"unknown"`，文本类指标缺失填空串。

**R06 60 字符折行规则**（`batch_ingest.py:wrap_line`、`make_readable`）
- 宽度 `READABLE_WIDTH=60`，按字符数而非显示宽度计。
- frontmatter 整体不折行；以 `#` 开头的标题行和空行原样保留；只折正文段落。
- 分词：连续的英文/数字/连接符 token（正则 `[A-Za-z0-9][A-Za-z0-9\-_.+/]*|.`）当不可拆整体，避免把 `Nafion` 拆成 `Na/fion`；中文按单字折。
- 续行去掉行首空格；单个 token 自身超宽（长 DOI/URL）则独占一行，不再拆。
- 可读版是生成物，永远不手改；`notes/` 是不折行唯一真源。新系统中可读版是 exports 的按需导出物。

**R07 表征方法前缀处理与命名规范**（AGENTS.md；`map_characterization.py:split_prefix`、`map_term`）
- 纯缩写技术直接大写：DEMS、XPS、TEM、STEM、XRD、NMR、SEM、AFM、EELS、ICP-OES、GC-MS。
- 前缀 `in situ`/`operando`/`ex situ` 与技术名之间用单个空格，不用连字符、不粘连（写 `in situ Raman`，不写 `insitu-Raman`、`in-situ-Raman`）。中文"原位"→ `in situ`，"工况下"→ `operando`，"非原位/离线"→ `ex situ`。
- 前缀只认小写后以 `<前缀> ` 或 `<前缀>-` 开头；剥离前缀后查表，查到再拼回；in situ 与 operando 是不同实验条件，绝不合并。
- 同一技术全库统一缩写，不并存缩写和全称；原文含糊时只列文中明确点名的技术，全文未点名则填 `[]`；纯计算论文填 `[]`。
- 映射不上：旧实现保留原文并加 `unmapped:` 前缀写回笔记，这是缺陷（第 5 节）；新系统应保留原文并登记到词表候选/review。

**R08 非期刊论文跳过规则**（`batch_ingest.py:EXTRACT_SYSTEM_PROMPT`、`run_one_batch`、`EXCLUDED_FOLDER_NAMES`）
- `is_journal_article` 为 false 的情形：教材/书籍章节、仪器操作或培训手册、技术报告、学位论文、会议海报或幻灯片、产品说明书、专利文本；摘录明显缺少期刊论文特征（无摘要段、无期刊 header、不像投稿格式）也判 false。研究论文和综述都算 true。
- 默认跳过并在 state 记 `skipped_non_journal`；`--no-skip-non-journal` 可关闭。
- 来源文件夹名为 `电镜资料` 的整体排除（用户 2026-07-18 要求，内容多为仪器手册/教材）。新系统做成可配置的排除规则。
- 判 false 时其余字段能填多少填多少。

**R09 各处相似度与数值阈值汇总**

| 阈值 | 数值 | 出处 |
|---|---|---|
| 标题查重 | 0.90 | `batch_ingest.py:TITLE_DUP_THRESHOLD`；`find_duplicate_titles.py --threshold` 默认；`build_topic_digest.py:find_near_duplicates`；`scan_new_papers.py:is_duplicate`（硬编码） |
| Crossref 标题采信 | 0.90 | `batch_ingest.py:CROSSREF_MATCH_THRESHOLD`；`scan_new_papers.py:CROSSREF_MATCH_THRESHOLD` |
| 文件名 SI 配对 | 0.82，且两边归一化后 ≥10 字符、非纯数字 | `batch_ingest.py:pair_files:FNAME_SIM_THRESHOLD` |
| 孤儿 SI 自动绑定 | ≥0.85 | `match_orphan_si.py:AUTO_APPLY_THRESHOLD` |
| 孤儿 SI 报告人工确认 | 0.55~0.85 | `match_orphan_si.py:REVIEW_THRESHOLD` |
| 扫描版判定 | strip 后少于 50 字符 | `batch_ingest.py:run_one_batch`、`ds.py:cmd_pdf_meta` |
| PDF 文字读取上限 | 200000 字符，不限页数 | `batch_ingest.py:extract_pdf_text`、`ds.py --max-chars` |
| 折行宽度 | 60 | `batch_ingest.py:READABLE_WIDTH` |
| 批大小默认 | 入库 15；重生成 20；性能抽取 20 | 各脚本 `--limit` |
| Crossref | `rows=5`，超时 10 秒 | 上述两函数 |
| 体检每类问题默认列出 | 5 条 | `check_library.sh:TRUNCATE_AT` |
| 孤儿 SI 取首页文字 | 1 页、3000 字符 | `match_orphan_si.py` |
| 回填取文字 | 前 12000 字符 | `backfill_fields.py:get_backfill_fields` |
| 本地 DOI 预查取文字 | 前 3 页、8000 字符 | `reconcile_state.py:extract_doi_locally` |
| 面板分页 / 最近新增条数 | 50 / 5 | `ui/app.py:PAGE_SIZE`、总览页 |
| OpenAI 客户端 | `backfill_fields.py` 与 `rename_citekeys.py` 用 `timeout=30, max_retries=1`；其余用 SDK 默认值（默认值待核实） | 各脚本 |

**R10 LLM 模型档位分工**（CLAUDE.md；各脚本 `--model` 默认值）
- 原则：纯结构化抽取/候选筛选用抽取档（flash），读者真正会看的内容或判断用总结档（pro）。
- 总结档：`batch_ingest.py`、`ds.py pdf-meta`（二者同时产出七节笔记正文）、`regenerate_notes.py`、`find_citations.py`（`--draft-model`、`--segment-model`）、`build_topic_digest.py --draft-model`、`word_auto_cite.py`（`--draft-model`、`--segment-model`）。
- 抽取档：`parse_search_results.py`、`scan_new_papers.py:deepseek_extract`、`extract_performance.py`、`match_orphan_si.py`、`backfill_fields.py`、`rename_citekeys.py`、`ds.py chat/json` 默认、面板"自然语言翻译命令"。
- 旧模型名 `deepseek-chat`、`deepseek-reasoner` 已弃用（AGENTS 使用指南记 2026-07-24 弃用），脚本里残留处已改成 flash/pro。
- 量大（几十篇以上）时先告知用户大概要处理多少篇（会花额度）。
- 深度精读、判断、关联已有笔记的任务不外包给廉价模型。

**R11 Word 重编号的两阶段替换**（`word_insert_citation.py:do_rebuild`）
- 先扫正文（References 标题之前），用 `\[(\d+(?:,\d+)*)\]` 找标记，按首次出现顺序给文献重新连续编号。
- 阶段一：每个旧标记整体替换成占位符 `⦃RENUM<i>⦄`；阶段二：占位符替换成新标记文本。原因：旧编号与新编号有重叠（如 1 与 7 互换）时直接顺序替换会互相覆盖。
- 替换时随时修正正文范围终点（占位符长度与原标记不同）。
- 然后删掉 References 小节整体并按新编号重写（标题用 Heading 1）。
- 只支持 `[n]` 括号样式（numbered、wiley、gbt7714）；nature 用上标无括号，纯文本层面无法与普通数字区分，不支持。
- 建议跑之前先保存文档；结果不对可撤销。
- Word 段落分隔符是 `\r` 不是 `\n`：判断"References 标题是否已存在"要按 `\r` 手动切行比对字符串，不能用 `re.MULTILINE` 的 `^$`（踩过的坑：匹配不到，导致每次插入都重复加标题）。

**R12 DOI 与 Crossref 其他踩坑**
- PDF 文字里没抽到 DOI 时，用 Crossref 按标题反查（纯 HTTP，不经 LLM）。
- 综述、学位论文、厂商说明书常无 DOI，必须靠标题相似度兜底查重。

**R13 frontmatter 解析的"吞换行"坑**（AGENTS.md；多处脚本已修）
- 旧正则里 `^field:\s*(.*)$` 在字段值为空时，`\s` 会吃掉换行，使取值变成下一行。正确写法 `[ \t]*`。新系统改用严格 YAML 解析，但迁移工具读旧笔记时仍要处理这种空值（`rating:` 后直接换行）。

**R14 tags 与 keywords 规则**
- tags：受控词表，1~4 个，用于粗筛；新增标签要说明理由并补进词表；不要为凑数把无关论文硬塞进电催化标签。
- keywords：自由词，5~10 个，写前先读 KEYWORDS，能复用就复用，避免近义词（DFT 与 first-principles 统一，Ir dissolution 与 iridium dissolution 统一）。
- 默认词表 29 个标签（`DEFAULT_TAG_VOCAB`）：`OER HER PEMWE AEMFC PEM界面 膜降解 IrOx CoOx RuOx IrCoOx 溶出 烧结 DFT AIMD NEB STEM cryoEM 原位表征 EELS 综述 方法学 电池 2D材料 钙钛矿 结构生物学 高分子 单原子催化 拉曼光谱 半导体光电`。这是领域定制，新系统做成可替换词表，不写死。
- status 流转：`unread → skimmed → read`。入库自动填七节后默认 `skimmed`（AI 摘录生成，未经人工验证），人工精读后才改 `read`。粗建档模式（正文留空、`unread`）仍应支持。
- 具体数值字段（泛函、+U、k 点、slab 尺寸等）只写文字里明确出现的，没提到就如实写"原文未提供该数值，建议查全文/SI"，绝不臆测。

**R15 `test_type` 词表与受控词表合并原则**
- `half-cell`、`MEA`、`full-cell`、`unknown`；器件级统一用 `MEA`，`device` 停用。半电池与 MEA 的数值不可比，条件要和数值绑在同一行。
- 教训：新增受控词表值前，先检查是否已有语义等价的值。

**R16 重复收录的取舍**（AGENTS.md；`resolve_duplicate.py`）
- 优先保留 citekey 里更能准确描述研究体系的版本（如 PEMWE 相关工作保留含 `PEMWE` 的那个）；两边同样准确，保留 DOI/keywords 更完整的一版。
- 劣势版本独有的更优字段并入保留版本。
- 单对重复可直接处理并在汇总里说明；成批（5 组以上）先列清单等确认。

**R17 红线**
- 绝不修改、移动、删除 EndNote 库（`STEM-AEM.enl`、`STEM-AEM.Data`）及 Reference 下各主题文件夹里的文件，从那里取 PDF 一律只复制。
- 不做批量删除，要清理先列清单给用户确认。新系统所有删除进回收区。
- 不确定某个操作是否安全时，输出打算做什么并停止，等人工确认。

**R18 inbox 清理规则**
- 成功入库且不在存疑清单的源文件删除；确认是库内已有条目重复（DOI/标题核对一致）的同样直接删除；只有存疑未配对（SI 找不到正文、DOI 核实不了）的留下。
- 数量较大或有任何不确定项时先列清单。

**R19 bib 格式**
- 默认 `@article`（会议/书籍才用 `@inproceedings`/`@book`）；字段 title/author/journal/year/doi，顺序不重要但必须齐全。
- `author` 用 `authors_full`，以 ` and ` 连接，不用 `et al.` 截断；`authors_full` 缺失才退回 `authors_display`。
- 追加前必须检查没有相同 DOI（大小写不敏感）。

**R20 INDEX 行格式**
- `| <citekey> | <year> | <title> | <tag1>, <tag2> | <status> | <SI标记> |`；SI 标记取 `PDF`/`Word`/`PDF+Word`（排序后以 `+` 连接），无 SI 留空；头部"共 N 篇"计数。新系统 INDEX 是导出物，计数由 exports 生成。

**R21 `authors` 与 `authors_full`**
- `authors` 是简短显示（"第一作者 et al." 或前三位分号分隔，单作者就是单作者）；`authors_full` 按原文顺序列全部，格式"名 姓"。

**R22 全文读取原则**（2026-07-19 改规则）
- 必须读全文而不是前几页，否则"质疑与局限""值得追的参考文献"系统性只能写占位话（不是模型偷懒，是输入没有那部分内容）。
- 读不到的内容如实说明，不要编。占位话写法：摘录范围内看不出局限时写"原文摘录部分未见明确讨论局限性，建议精读全文/结论部分核实"；无参考文献线索时写"摘录部分未见明确引用线索，建议查全文参考文献列表"。

**R23 状态/缓存复用原则**
- 抽取全文存 `extracted-text/<citekey>.txt`，以后加字段或改逻辑优先从缓存读，不重新读 PDF。新系统该缓存是真源之一（`text/`）。
- 断点续跑：入库、重生成、性能抽取各有自己的状态文件；`--force`/单篇强制重跑需先清旧结果避免重复行。

**R24 找新文章的搜索策略**（CLAUDE.md，2026-07-18 教训）
- 不能锚定单一主题词。曾因必含 `iridium` 漏掉标题主语是 ruthenium oxide、实为 Ir 掺杂稳定 RuOx 的 Nature Nanotechnology 论文。
- 同一批要单独搜"low-iridium"、"ruthenium...PEM water electrolysis"、"acidic OER catalyst"等不预设元素在标题里的变体，或按期刊逐个扫目录，或按高产课题组检索。
- 同一领域按子类分别检索（Ir 基/Ru 基/非贵金属基各一轮）。
- WebSearch 单次约 10 条，做不到数学意义上的"全面"；新系统用 OpenAlex 按期刊+时间窗分页拉取，可更接近穷举，但仍不得承诺"绝对全面"。

**R25 分类规则**（`scan_new_papers.py:classify_category`，领域专属）
- 含 Ir 与 Ru → Ir-Ru-mixed；仅 Ir → Ir-based；仅 Ru → Ru-based；命中 cobalt/nickel/manganese/iron/CoO/NiO/MnO/FeO/non-PGM/non-precious/earth-abundant/platinum-group-metal-free → Non-PGM；否则 Unclear。
- 候选自带 `category` 时优先用候选的。
- 分类是关键词粗分，不是语义理解；交叉体系应人工核实，不能当最终结论。

**R26 引文献规则**（`find_citations.py`；CLAUDE.md）
- 三值：support（方向一致可直接引）、contradict（数据或结论与陈述句矛盾，要指出矛盾在哪个分句）、unclear（信息不足）。
- 某篇的观测数据支持前半句、整体结论反对后半句时必须拆开说，不得笼统打一个标签。
- 理由必须基于摘要里实际出现的内容，不许编造。
- 最终引用决定权在人，不能直接照抄 `--draft` 输出；库内判断偏保守（摘要没有一模一样的措辞就打 unclear）时，人工可基于笔记全文 override。
- 整段模式：自动跳过作者自己的论点/创新点陈述，并在逐句清单里标注"无需引用"及原因；一段话通常拆 2~5 条独立论点，不过度拆分也不遗漏。
- 每句 Word 自动插入只取第一条 support。
- 踩过的坑：同一类表征（Ir L3-edge XANES 白线随电位正移）在不同体系里被不同论文报成相反趋势，只靠关键词会引到反对论点的文献。

**R27 重生成与性能抽取的保护字段**
- 重生成不覆盖：citekey、title、authors、authors_full、year、journal、doi、tags、status、rating、related、si_files、added（已核实的元数据或人工判断字段）。
- 默认跳过 `status: read`（人工精读过，不轻易覆盖）。

**R28 面板入库路径与脚本路径的差异**
- 面板"入库"用无人值守路径，不经过查重/DOI/SI 的人工审核；需要核实时仍要回到对话流程。新系统统一为"自动 + 存疑进 review"。

**R29 体检检查项**（`check_library.sh`）
1. 有 PDF 但缺笔记；2. 有笔记但缺 PDF；3. 有 PDF 但 bib 缺条目；4. bib 有条目但缺 PDF；5. notes 与 notes-readable 双向缺失；6. notes 有但 extracted-text 缺；7. bib 重复 DOI（排除占位值）；8. 笔记 `si_files` 引用的文件在 papers 里找不到；9. papers 里有 `_SI` 文件但没有笔记引用（孤儿 SI）；10. 全库标题相似度查重；11. inbox 有待整理 PDF（仅提示）。新系统里 3/4/5 随 bib、readable 变成导出物而改为"导出物是否过期"；新增 frontmatter 严格校验、citekey 格式、索引与文件一致性、台账一致性。

**R30 Windows 环境坑**
- 控制台默认 GBK，输出中文要把 stdout 重配 UTF-8（多个脚本 `sys.stdout.reconfigure`）。
- PATH 里的 `bash` 可能解析到 WSL 的 bash.exe，与 Git Bash 不兼容（报 HCS/CreateVm 错误）；面板显式探测 `C:\Program Files\Git\bin\bash.exe`。新系统不再依赖 shell 脚本。
- Bash 工具里 `python` 不可用，用 `py` 启动器；PowerShell 重定向会产生 UTF-16 文件（`_dryrun1.txt` 即是）。

**R31 Streamlit 前端踩坑**（不继承实现，只记录以免在新前端重蹈）
- `st.tabs()` 不记跨 rerun 的当前标签页；滚动容器是 `[data-testid="stMain"]` 而非 `window`；`components.html` 内容一字不差时 iframe 不重新加载，需要 nonce；按钮点击后画面被拉回别的标签页会让用户觉得"没反应"。

**R32 性能数据抽取**
- 严禁编造数值，只抽取正文/摘要里明确写出的数字；没把握填 null/`unknown`/空串，宁可漏抽。
- 论文根本不是电催化性能相关（如纯理论/表征方法综述）则 rows 为空数组。
- 条件（电解液、温度、电流密度基准、测试形式）必须与数值绑在同一行。
- `degradation_rate` 保留原文单位描述（如 `0.02 mV/h`、`5% after 100h`）。

**R33 主题综述工作流**
- 标准流程：筛选摘要 → 核对每个 `[[citekey]]` 真实存在 → 补"观点分歧/未来方向/数据缺口"这类需判断的小节 → 定稿 → docx（必做，不问用户）→ 读回校验。
- 初稿禁止编造摘要之外的内容；摘要信息不够就写"资料不足"。

**R34 笔记正文要求**
- 正文中文为主，术语、化学式、参数保留英文原写法；七节固定：三句话总结、研究问题与核心结论、方法要点、关键图表与数据、与我课题的关联、质疑与局限、值得追的参考文献。
- 计算类方法要点必须含泛函、+U、k 点/ENCUT、模型尺寸；实验类必须含表征手段、关键条件、样品体系。
- 与课题关联度低时如实说明，不牵强附会。

**R35 EndNote 导入**
- RIS 默认，BibTeX 备选；导入选项 Duplicates 选 Discard Duplicates，由 EndNote 按 DOI/标题去重；不附 PDF。

**R36 Word 引用样式**
- 四种样式是近似风格，不是严格官方格式；library.bib 不存卷期页，投稿前需自行补齐。
- numbered：`n. 作者, 《标题》, 期刊, 年份, doi:xxx.`（作者超过 3 位用 `et al.`）；nature：上标编号，`姓, 名缩写`，2 作者用 `&`，超过 2 位 `et al.`；wiley：`[n] 名缩写. 姓, 期刊, 年份`；gbt7714：`[n] 姓 名缩写. 标题[J]. 期刊, 年份`，最多列 3 位作者后加 `, et al`。
- 状态记在 `<文档名>.citemap.json`；不会自动保存文档；不是 Word 域代码。

**R37 sync/count 类行为**
- 入库、删除后同步 INDEX 的"共 N 篇"；新系统计数由 exports 查索引得出（旧实现缺陷见第 5 节）。

**R38 排除痕迹**
- 用户明确排除的文献在状态里保留痕迹（`excluded_by_user`），重跑同一来源不得重新入库。

**R39 Excel 导出**
- 列固定 9 列，宽度 `[55,35,30,8,22,35,18,14,30]`；`status=new` 才进 summary；汇总行格式"共 N 条候选, M 条需要下载（按分类列出, K 条已在库跳过）"。

**R40 CLAUDE.md 的角色边界**
- 维护者（Claude）不写笔记内容，不外包需要深度判断的精读，只搭骨架、维护一致性、体检；规则只改 `AGENTS.md` 一处，避免两边漂移。新系统对应：DATA_MODEL 为唯一数据真源。

---

## 4. LLM prompt 清单

通用：所有调用默认 `temperature=0`；除"拆论点输出之外的 Markdown 型"外，均用 `response_format={"type":"json_object"}`；旧实现无统一重试/限流/输出校验（见第 5 节），新系统由 `adapters.llm` 统一提供。每节标明字段名、类型、约束。

### P01 论文入库抽取 + 七节笔记（`batch_ingest.py:EXTRACT_SYSTEM_PROMPT`）
- 用途：从论文全文同时抽元数据并写精读笔记正文；被 `ds.py pdf-meta`、`regenerate_notes.py` 复用。
- 档位：总结档。
- 输入：PDF 全文文字（上限 200000 字符）；system prompt 里动态注入：标签受控词表（`tag_vocab.txt`，缺则默认 29 个）和课题背景（`research_profile.md`，缺则写入"未配置课题背景"的说明）。
- 关键约束句：只输出一个 JSON 对象，无解释、无 markdown 围栏；缺失的元数据填 `"unknown"`，绝不编造 DOI 或年份；正文基于给定文字如实总结，信息不足就明说，不脑补；只根据给定文字判断，不联想文字之外的知识；若只拿到部分文本，缺的部分要如实说明。
- 返回字段：

| 字段 | 类型 | 约束 |
|---|---|---|
| `is_journal_article` | bool | 期刊论文（研究或综述）为 true；教材、手册、报告、学位论文、海报、说明书、专利为 false（R08） |
| `title` | string | 英文原题 |
| `authors_display` | string | "第一作者 et al." 或前三位作者分号分隔 |
| `authors_full` | string[] | 全部作者，原文顺序，每人"名 姓" |
| `year` | int | 4 位整数 |
| `journal` | string | 期刊全名 |
| `doi` | string | 找不到填 `"N/A"` |
| `journal_abbr` | string | 无空格无句点；全大写业界缩写保持全大写，其余驼峰式；注意 prompt 示例里仍含 `ACIE`，与规范冲突（第 5 节） |
| `condensed_title` | string | 3~6 个英文单词，连字符连接，元素符号与领域缩写按规范大小写 |
| `tags` | string[] | 1~4 个，优先词表，必要时才新增 1 个 |
| `keywords` | string[] | 5~10 个，英文为主，不确定就少给 |
| `类型` | string | `计算`/`实验`/`计算+实验`/`综述` 之一 |
| `方法关键词` | string | 计算类写泛函/AIMD；实验类写主要表征手段，仅写文中能确定的 |
| `表征方法` | string[] | R07 命名规范；含糊则不编，纯计算填 `[]` |
| `体系` | string | 研究对象简述 |
| `summary_3lines` | string | 三句话总结，中文 |
| `problem_conclusion` | string | 3~6 句 |
| `method_points` | string | 计算类含泛函/+U/k 点/ENCUT/模型尺寸，缺失写"原文未提供该数值，建议查全文/SI"；实验类含表征/条件/制备 |
| `key_results` | string | 关键数值结果带原文单位，只描述文字里能读到的 |
| `relevance` | string | 与课题的关联；关联度低要如实说，未配置课题背景要如实说 |
| `caveats` | string | 质疑与局限，见 R22 占位话 |
| `further_reading` | string | 关键被引工作线索，见 R22 占位话 |

### P02 回填字段（`backfill_fields.py:BACKFILL_PROMPT`）
- 用途：一次性给旧笔记补 `authors_full` 和 `表征方法`。
- 档位：抽取档。
- 输入："标题: ...\n\n正文摘录:" 加全文前 12000 字符。
- 约束：只根据给定文字，不编造；找不到完整作者名单就尽量列能确定的，不要只写一人；表征方法规则同 R07。
- 返回：`authors_full` string[]；`表征方法` string[]。
- 迁移处理：只在 `papernest.migrate` 里需要。

### P03 重命名字段（`rename_citekeys.py:RENAME_PROMPT`）
- 用途：旧格式 citekey 迁移时，由标题和期刊生成期刊简称与提炼标题。
- 档位：抽取档。
- 输入："标题: ...\n期刊: ..."。
- 约束：只根据给定标题和期刊判断，不编造；prompt 示例里同样含 `ACIE`（冲突，见第 5 节）。
- 返回：`journal_abbr` string；`condensed_title` string（规则同 P01）。
- 迁移处理：仅迁移时用；新系统 citekey 由 `core.citekey` 结合期刊映射表确定性生成，LLM 只给 `condensed_title`。

### P04 识别 SI 所属主论文（`match_orphan_si.py:IDENTIFY_PROMPT`）
- 用途：读疑似 SI 的首页文字，识别它声明所属的主论文标题。
- 档位：抽取档。
- 输入：SI 首页文字（最多 3000 字符）。
- 约束：只输出 JSON；识别不到就诚实说识别不到（`candidate_title` 留空），不编造标题。
- 返回：`is_si` bool；`candidate_title` string（识别不到为空串）；`confidence` 字符串，取 `high`/`medium`/`low`（旧代码读取了 JSON 但没有使用这个字段）。

### P05 性能数据抽取（`extract_performance.py:SYSTEM_PROMPT`）
- 用途：从全文抽带完整测试条件的性能数据组。
- 档位：抽取档。
- 输入：`extracted-text` 全文。
- 关键约束：每组独立测试条件算一行，不把不同条件混进同一行；严禁编造数值，没把握填 null/`unknown`/空串，宁可漏抽；论文无可提取性能数据则返回空数组；器件级测试统一填 `MEA`，不用 `device`。
- 返回：`{"rows":[...]}`，每行字段：

| 字段 | 类型 | 约束 |
|---|---|---|
| `test_type` | string | `half-cell`/`MEA`/`full-cell`/`unknown` |
| `reaction` | string | OER/HER/ORR/PEMWE/AEMWE/PEMFC 等，无则 `unknown` |
| `electrolyte` | string | 电解液或膜类型，无则 `unknown` |
| `temperature_C` | number 或 null | 没提到填 null，不假设室温 |
| `catalyst_loading_mg_cm2` | number 或 null | |
| `current_density_ref_mA_cm2` | number 或 null | 过电位/电压对应的电流密度基准 |
| `overpotential_mV` | number 或 null | |
| `cell_voltage_V` | number 或 null | 常见于 MEA |
| `tafel_slope_mV_dec` | number 或 null | |
| `stability_duration_h` | number 或 null | |
| `degradation_rate` | string | 保留原文单位描述，无则空串 |
| `other_metrics` | string | 法拉第效率、TOF、质量活性等，无则空串 |
| `source_location` | string | 如 `Figure 3a`、`Table 1`，无则空串 |

- 注意：prompt 里写"可能不含全文，只有前几页"，是历史遗留措辞，新系统喂全文时应更新。

### P06 引文方向判断（`find_citations.py:DRAFT_SYSTEM`）
- 用途：对一句陈述句和一批候选摘要，逐篇判断 support/contradict/unclear。
- 档位：总结档（`--draft-model`）。
- 输入："陈述句: ...\n\n候选文献:" 加每篇候选的 citekey、年份、期刊、title、体系、方法要点、关键图表与数据。
- 关键约束：理由必须基于摘要里实际出现的内容，不许编造；部分支持部分反对要拆开说；输出必须带论文标题，从摘要原样照抄不翻译不缩写。
- 旧输出是 Markdown 列表（`- **citekey** — 《标题》 (期刊, 年份) [support/contradict/unclear]: 理由`），再由 `word_auto_cite.py:CITATION_LINE_RE` 用正则解析，易碎（第 5 节）。新系统要求结构化 JSON。
- 建议返回字段：

| 字段 | 类型 | 约束 |
|---|---|---|
| `citekey` | string | 必须在候选集合里 |
| `verdict` | string | `support`/`contradict`/`unclear` |
| `reason` | string | 基于摘要内容的一句话理由 |
| `contradicts_clause` | string 或 null | verdict 为 contradict 或部分矛盾时，指出矛盾在陈述句的哪个分句 |

### P07 拆论点（`find_citations.py:SEGMENT_SYSTEM`）
- 用途：把一段正文拆成若干独立论点，判断是否需要引用，并给检索关键词正则。
- 档位：总结档（`--segment-model`）。
- 输入：整段正文（`word_auto_cite.py` 则把整份文档正文一次性喂入）。
- 关键约束：一段话通常拆出 2~5 条；不过度拆分、不遗漏；作者自己的创新点表述、纯逻辑推导、过渡句不需要引用。
- 返回：`{"claims":[...]}`，每条：

| 字段 | 类型 | 约束 |
|---|---|---|
| `text` | string | 论点原文片段，尽量原样摘录 |
| `needs_citation` | bool | |
| `reason_if_not` | string | needs_citation 为 false 时说明原因 |
| `keyword_regex` | string | needs_citation 为 true 时给检索正则，英文为主，`|` 分隔同义词（旧实现不校验正则合法性，见第 5 节） |

### P08 主题综述初稿（`build_topic_digest.py --draft` 里的内联 system prompt）
- 用途：基于结构化摘要起草中文综述初稿。
- 档位：总结档（`--draft-model`）。
- 输入：digest 全文（每篇 citekey/标题/年份/期刊/体系/方法要点/关键图表与数据）。
- 关键约束：归出 3~6 个大类，每类一段思路小结加要点列表；每条必须用 `[[citekey]]` 标注出处，citekey 原样照抄不得编造或改写；写一节"方法-性能关联的整体趋势"；严禁编造摘要之外的内容，信息不够写"资料不足"；Markdown 输出，标题层级 `##`/`###`。
- 输出：Markdown 文本（非 JSON）。新系统应要求结构化引用字段，便于机器校验 citekey。

### P09 搜索结果抽候选（`parse_search_results.py:SYSTEM_PROMPT`）
- 用途：从网页搜索原始文字里抽候选论文。
- 档位：抽取档。
- 输入："这批搜索的目标: ...\n\n搜索结果原文:" 加原始文字。
- 关键约束：同一论文多次出现只输出一次；公司主页、专利、新闻稿、无关产品页不输出；综述/perspective 照实输出；不确定字段留 null，不猜 DOI（猜错比没有更糟）。
- 返回：`{"candidates":[...]}`，每条 `title`（string，尽量原样）、`doi`（string 或 null）、`journal`（string 或 null）、`year`（int 或 null）、`category_hint`（`Ir-based`/`Ru-based`/`Ir-Ru-mixed`/`Non-PGM`/`Unclear`）。
- 新系统：不再需要，除非保留"贴文字导入"后备入口。

### P10 乱文字抽单篇元数据（`scan_new_papers.py:deepseek_extract` 内联 prompt）
- 用途：没有 DOI、也没有标题的一段抓取文字，抽一篇论文的元数据。
- 档位：抽取档。
- 输入：原始文字（和可选 link）。
- 约束：只抽取文字里明确出现的信息，没把握留空/null，不编造。
- 返回：`title` string；`authors` string[]；`journal` string；`year` int 或 null；`doi` string（无则 `N/A`）。

### P11 自然语言翻译成命令（`ui/app.py` 命令页内联 prompt）
- 用途：把用户的一句话翻译成可在库根目录执行的一条命令。
- 档位：抽取档。
- 约束：只输出命令本身，无解释；没把握就输出以 `#` 开头的中文说明，不瞎编参数。
- 新系统：不继承（见第 2 节），不需要此 prompt。

---

## 5. 回归用例

`ARCHITECTURE.md` 规定本节每条都必须有同名测试。前 18 条来自任务给出的已知缺陷，其后为阅读代码时新发现的缺陷（标注"新发现"）。

### 5.1 已知缺陷

| 用例名 | 场景 | 期望行为 | 归属模块 |
|---|---|---|---|
| `test_index_count_with_digit_leading_citekeys` | `sync_index_count` 用 `^\|\s*[A-Z]` 靠首字母大写识别数据行；citekey 改版后以数字开头，计数恒为 0（旧库 `INDEX.md` 头部实测写"共 0 篇"，而 `notes/` 有 406 篇） | INDEX 的篇数来自索引查询，数字开头、`unknown-` 开头、小写开头的 citekey 都被计入 | `services.exports` |
| `test_remove_does_not_delete_prefix_siblings` | `remove_citekeys.remove_one` 用 `papers.glob(f"{citekey}*")`，删 `2025-X-Foo` 会连 `2025-X-Foo-2.pdf`、`2025-X-Foo-2_SI.pdf` 一起删 | 删除只作用于精确 citekey 的 `<citekey>.pdf` 与 `<citekey>_SI.*`，姐妹条目完好，且进回收区 | `services.maintenance` |
| `test_merge_duplicate_si_references_not_dangling` | `resolve_duplicate` 把 loser 的 `si_files` 并入 winner，却把 `papers/<loser>_SI.*` 删掉，winner 的 `si_files` 指向已不存在的 `<loser>_SI.pdf` | 合并时把 loser 的 SI 文件改名并入 winner（`<winner>_SI...`），`si_files` 与磁盘一致，doctor 无"引用不存在"报告 | `services.maintenance` |
| `test_regenerate_rejects_incomplete_llm_output` | `regenerate_notes.rebuild_note` 用 `meta.get(key, "")`，LLM 漏掉任一正文字段就把小节写成空 | 返回缺字段、字段为空或类型不对时，拒绝写入、保留旧笔记、记入失败队列并说明缺哪些字段 | `services.regenerate` |
| `test_regenerate_keeps_readable_export_fresh` | 旧实现重生成后不同步 `notes-readable/`，需要另跑脚本 | 重生成后可读导出被标记过期或自动重新生成；不存在两份真源不同步的状态 | `services.regenerate` |
| `test_rename_updates_every_location` | 旧的改名实现有三份（`rename_citekeys`、`rename_journal_abbr`、`resolve_duplicate`/`remove_citekeys`），覆盖位置不一致：前者漏 `extracted-text`；`rename_journal_abbr` 不碰状态文件；都不碰 `data/performance.csv`；`related` 字段与 `[[citekey]]` 引用处理各异 | 单一改名实现，一次事务改全：笔记（含 `related`）、papers 与 SI 与 `si_files`、全文缓存、入库台账中的 citekey、性能数据行（`citekey`、`row_id`）、其他笔记与 `topics/` 里的 `[[citekey]]`，全部同事务完成或全部回滚 | `services.maintenance` |
| `test_rename_text_replacement_respects_citekey_boundaries` | 新发现：`rename_journal_abbr` 对全库笔记 `text.replace(old_ck, new_ck)`，`old_ck` 是 `X` 时会把 `X-2` 里的子串一并改写 | 引用替换只匹配完整 citekey（边界为非 citekey 字符），`X-2` 不受影响 | `services.maintenance` |
| `test_bib_nested_braces_and_entry_types` | 旧 bib 正则 `\{([^}]*)\}` 遇嵌套花括号（`{Ir}O$_2$`、`{DFT}`）截断，且只认 `@article` | 导入旧 bib 的解析器正确处理嵌套花括号、`@inproceedings`/`@book`/`@misc` 等类型、字段换行、引号定界值 | `papernest.migrate` |
| `test_bib_export_roundtrip_with_braces` | 导出 bib 时标题含 `{`、`}`、`&`、`%`、`_`、`$` | 导出的 bib 能被标准 BibTeX 解析器读回，保大小写用的花括号保留，特殊字符正确转义 | `services.exports` |
| `test_list_fields_with_commas_roundtrip` | 列表字段按逗号切分（`build_keyword_index.sh`、`map_characterization.py:parse_list_line`、`resolve_duplicate`、`ui/app.py:_fm_list_field`），`[Ir(III), Ru(IV) oxide]`、`"Smith, Jr."` 一类值被切坏 | 列表字段是真正的 YAML 序列，含逗号、引号、冒号、方括号的值往返不变；迁移时旧的内联数组被正确还原 | `core.note_io` |
| `test_author_names_not_split_by_last_word` | 作者姓名一律"最后一个词当姓"（`export_for_endnote:to_ris`、`word_insert_citation:_surname_initials`），`van der Waals`、`de la Cruz`、`Jr.`、单名、中文姓名都被切错 | 作者以结构化 given/family 保存（Crossref 提供的优先），RIS 与引用样式按结构化字段输出；无结构化来源时保留原文序列化，不猜姓 | `core.models`、`services.exports` |
| `test_ingest_resume_keyed_by_sha256` | 断点状态以源文件绝对路径为 key（`.ingest_state.json`），文件移动、改名、换目录后被当新文件重复调用 LLM；面板还要兼容三种路径写法 | 台账以文件 sha256 为 key；同内容不同路径视为同一文件；换盘符、改名、复制后续跑不重复处理 | `core.state`、`services.ingest` |
| `test_concurrent_writes_no_lost_update` | 旧系统无锁无事务，多进程（面板 + 命令行）同时追加 `library.bib`、改 `INDEX.md`、写状态文件会丢更新 | 并发写同一库不丢更新：文件锁 + 原子写；两个任务同时入库两篇，两篇都在 | `core.library`、`core.state` |
| `test_state_write_is_atomic` | 新发现：各 `save_state` 直接 `write_text`，进程在写到一半被杀会留下损坏的 JSON，之后整条流水线崩溃 | 写入先落临时文件再原子替换；崩溃后状态要么是旧版要么是新版 | `core.state`、`core.library` |
| `test_notes_written_with_lf_only` | 部分脚本 `write_text` 不带 `newline="\n"`（`resolve_duplicate`、`regenerate_notes`、`rename_journal_abbr`、`find_citations`），在 Windows 写出 CRLF，与其他脚本写的 LF 混用，diff 噪声大，bash/正则工具行为不一 | 所有文本一律 UTF-8 + LF 写出；读取时容忍 CRLF | `core.note_io`、`core.library` |
| `test_frontmatter_values_with_colon_roundtrip` | 旧笔记写 frontmatter 时值不加引号（`batch_ingest:note_content`），标题或体系含 `: ` 时严格 YAML 解析失败（任务说明记为 406 篇里 71 篇；旧库 title 含 `: ` 的有 48 篇） | 写出的 frontmatter 一律能被严格 YAML 解析并往返；`migrate` 能修复旧笔记并报告修复条数，对 406 篇实测零解析失败 | `core.note_io`、`papernest.migrate` |
| `test_empty_field_does_not_swallow_newline` | 用 `\s*` 的正则在空值字段（`rating:`）上吞换行，取到下一行内容（`map_characterization.FRONTMATTER_LIST_RE` 仍留 `\s*`；`backfill_fields`、`rename_citekeys` 的 `title:\s*(.*)$` 同样有隐患） | 空值字段读成空，不串行；解析统一走 YAML 库而非正则 | `core.note_io` |
| `test_word_auto_cite_parses_structured_verdicts` | `word_auto_cite` 用 `CITATION_LINE_RE` 解析 LLM 的 Markdown 列表；标题里含 `[`、`*`、换行，或模型多输出一行就解析丢失 | LLM 判断以 JSON 返回并按 schema 校验；解析失败重试，不是静默当作无 support | `services.citations`、`services.word` |
| `test_word_locate_sentence_over_255_chars` | Word `Find` 对超过约 255 字符的文本定位失败；`locate_sentence` 没有长度保护，长句被静默跳过 | 长句分段（取句首与句尾锚点）或改用字符偏移定位，仍能找到并在句尾插入 | `services.word` |
| `test_llm_retry_ratelimit_and_output_validation` | 旧 LLM 调用无统一重试/限流/输出校验：429/5xx 直接抛，`json.loads` 失败崩批，字段类型不对写进笔记 | 统一重试（指数退避、可重试错误分类）、并发限流、按 schema 校验与有限次修复重试；最终失败进失败队列，不写坏数据 | `adapters.llm` |
| `test_journal_abbr_canonical_mapping` | 期刊缩写无映射表，靠 LLM 现编；prompt 里仍写 `ACIE`，与规范冲突（曾导致 ACIE 与 AngewChemIntEd 并存） | 缩写来自 `core.vocab` 映射表（期刊全名与别名 → 唯一缩写）；未登记的期刊进 review 登记，不让 LLM 自造；`ACIE` 一律映射到 `AngewChemIntEd` | `core.vocab`、`core.citekey` |
| `test_scanned_pdf_flagged_not_silently_skipped` | 扫描版 PDF 抽不出文字（strip 后少于 50 字符）被直接跳过或报错，用户不知道 | 标记 `needs_ocr` 进 review，保留源文件，不入库也不删；可选 OCR 回退 | `adapters.pdf_text`、`services.review` |
| `test_si_extension_case_normalized` | `ingest_from_meta` 的 SI 目标名用 `si_src.suffix`（原样大小写），`batch_ingest`、`match_orphan_si` 用 `.lower()`；schema 的 `si_files` 模式只认小写扩展名，`.PDF` 会通不过校验 | SI 扩展名统一小写，磁盘文件名与 `si_files` 一致 | `services.ingest`、`services.si_pairing` |
| `test_unmapped_prefix_not_in_frontmatter` | `map_characterization` 把映射不上的词条写成 `unmapped:<原文>` 回笔记，污染关键词索引（旧库实测 121 篇笔记含该前缀） | 笔记里保留原文词条；未映射项登记到词表候选/review，索引不出现 `unmapped:`；`migrate` 清理旧前缀 | `services.maintenance`、`core.vocab` |

### 5.2 新发现的缺陷

| 用例名 | 场景 | 期望行为 | 归属模块 |
|---|---|---|---|
| `test_multiple_si_same_extension_no_overwrite` | `batch_ingest` 为每个 SI 生成 `<citekey>_SI<ext>`；一篇论文有两个 pdf SI 时目标名相同，后者覆盖前者，`si_files` 里还重复列同一文件名（AGENTS"扩展名自然区分"只对不同扩展名成立） | 同扩展名的多个 SI 有稳定的区分后缀（具体命名由 DATA_MODEL 定），互不覆盖，`si_files` 无重复 | `services.si_pairing`、`services.ingest` |
| `test_crossref_adopts_only_journal_articles` | 新发现：`lookup_metadata_via_crossref` 只排除 `type=="component"`，注释声称只选 journal-article 但代码不检查；同标题的 posted-content（预印本）、book-chapter 也会被采信，DOI 可能是预印本的。`scan_new_papers.crossref_title_lookup` 同样 | 只采信 `journal-article`（综述等期刊文章类型按白名单）；预印本与正式版并存时优先正式版 | `adapters.crossref` |
| `test_crossref_title_html_tags_stripped_on_ingest` | `batch_ingest` 采信 Crossref 标题时不去 HTML 标签；`scan_new_papers` 只在 DOI 直查分支去标签。带 `<i>`、`<sub>` 的标题会进 frontmatter、bib、标题查重 | 所有来自 Crossref 的标题统一去标签、折叠空白、Unicode 归一后再使用 | `adapters.crossref`、`core.textsim` |
| `test_year_selection_consistent_across_ingest_and_discovery` | 入库年份取值顺序含 `created`，查新不含；同一论文在两处年份可能不同，影响 citekey 与去重 | 年份取值规则单一定义（优先级一处维护），入库与查新共用 | `adapters.crossref` |
| `test_title_dedupe_does_not_bleed_across_bib_entries` | 新发现：`existing_titles_with_doi` 用一条跨条目的 `re.S` 非贪婪正则取 title 与 doi；某条目缺 doi 字段时，会把它的标题与下一条目的 DOI 配对，造成误判重复或漏判 | 查重数据来自结构化笔记/索引，不再用 bib 正则；迁移时按条目解析 | `services.dedupe`、`core.index` |
| `test_missing_doi_placeholders_single_definition` | 四份不一致的缺失 DOI 占位集合（8/6/6/8 项，且大小写、引号处理各异） | 只有一处定义（`core.textsim` 或 `core.models`），被 dedupe、maintenance、discovery、doctor 共用 | `services.dedupe` |
| `test_doi_normalization_for_candidates` | 新发现：`scan_new_papers.crossref_lookup` 直接把候选 DOI 拼进 URL，不做 URL 解码、不去 `https://doi.org/` 前缀与尾随标点，不做 URL 编码；LLM 给的 DOI 常带这些 | 入口统一规范化 DOI（去前缀、去尾标点、小写比较、URL 编码发请求） | `adapters.crossref`、`services.discovery` |
| `test_classify_category_no_substring_false_positive` | 新发现：`ELEMENT_TOKEN_RE=[A-Z][a-z]?` 会从 `Iron`、`Irradiation`、`Irregular` 切出 `Ir`，从 `Ruddlesden`、`Rubber` 切出 `Ru`，导致误分到 Ir-based/Ru-based | 分类按元素符号词边界与化学式语法识别，不把普通英文单词的开头当元素 | `services.discovery`、`core.vocab` |
| `test_characterization_prefix_variants_normalized` | 新发现：`split_prefix` 只认 `in situ `/`in situ-`/`operando`/`ex situ`；`in-situ Raman`、`insitu-Raman`、`In Situ XRD` 变体都不被识别，落入 unmapped | 前缀变体（连字符、粘连、大小写）统一归一到 `in situ`/`operando`/`ex situ` 后再查表 | `services.maintenance`、`core.vocab` |
| `test_ingest_from_meta_checks_non_journal_and_missing_year` | 新发现：`ingest_from_meta` 不检查 `is_journal_article`，且直接用 `meta["year"]` 拼 citekey；`year` 为 `unknown` 时产生 `unknown-AdvFunctMater-...`（旧库实测有 5 篇不以数字开头），违反 schema `^[0-9]{4}-` | 入库统一检查：非期刊进 review，年份或期刊缺失进 review，不生成不合法 citekey | `services.ingest`、`core.citekey` |
| `test_citekey_collision_case_insensitive` | 新发现：撞名检查区分大小写（`key in taken`），但 Windows 文件系统不区分大小写；`2025-JACS-Ir-OER` 与 `2025-JACS-IR-OER` 会在 `papers/`、`notes/` 里互相覆盖。`ingest_from_meta` 的已占用集合只含 `notes/`，`batch_ingest` 含 bib+notes，也不一致 | 撞名检查大小写不敏感，且覆盖所有存储（笔记、papers、台账、回收区） | `core.citekey` |
| `test_ingest_is_atomic_on_failure` | 新发现：入库是顺序写 PDF、SI、全文、bib、笔记、INDEX，中途失败（磁盘满、权限、LLM 返回非法）会留下孤儿 PDF 或半条记录；`batch_ingest` 异常只记 state error | 一篇论文的入库是一个事务：要么六处都完成，要么全部回滚，失败进台账 | `services.ingest`、`core.library` |
| `test_make_readable_frontmatter_boundary` | 新发现：`make_readable` 用 `index("---", 3)` 找 frontmatter 结束，值里含 `---`（如标题里的破折号写法）会提前截断，后半部分当正文折行 | 可读导出按结构化解析的 frontmatter/正文边界处理，不用字符串搜索 | `services.exports` |
| `test_index_export_escapes_pipes` | 新发现：INDEX 表格行直接拼接标题，标题含 `|` 会破坏表格列 | 导出的 Markdown 表格对 `|` 转义 | `services.exports` |
| `test_top_journals_match_normalizes_journal_names` | 新发现：顶刊判断是 `note["journal"] in journal_set` 的逐字比对；`Angewandte Chemie`、`Angew. Chem. Int. Ed.`、`J. Am. Chem. Soc.` 等写法不命中，静默漏掉 | 比对前经期刊映射表归一到规范名与缩写 | `core.vocab` |
| `test_citation_candidates_capped_and_regex_validated` | 新发现：`find_citations`/`word_auto_cite` 对 LLM 给的 `keyword_regex` 不校验，非法正则让整次运行崩溃、病态正则可能卡死；候选数无上限，全部塞进一次 prompt 可能超上下文；整份文档正文一次性喂拆句 prompt | 正则校验与超时保护；候选分批或截断并保留相关性排序；长文档分块拆句；缺 `keyword_regex` 字段不崩 | `services.citations`、`services.word` |
| `test_word_rebuild_ignores_non_citation_brackets` | 新发现：`--rebuild` 用 `\[(\d+(?:,\d+)*)\]` 匹配正文里任何 `[n]`（含用户手写的 `[1]`、化学符号、公式）；不在 citemap 里的编号会被静默丢出标记，可能删掉用户文字；`[1-3]` 区间写法不识别 | 只处理本系统插入过的标记（可用隐藏书签或内容控件标识）；遇到未知编号不删除并提示 | `services.word` |
| `test_word_references_heading_offset_with_fields_or_tables` | 新发现（待核实）：`find_references_heading_start` 用 `doc.Content.Text` 的字符偏移当 `doc.Range(...)` 的位置，文档含域代码、表格单元格标记、隐藏文字时两者偏移可能不一致，导致删除范围错位 | 用 Word 对象模型直接定位 References 段落，不用文本偏移换算；含表格/域代码的文档里 rebuild 不破坏正文 | `services.word` |
| `test_orphan_si_word_documents_text_extraction` | 新发现（待核实）：`match_orphan_si` 对 `.docx`/`.doc` 也调用 pymupdf 抽文字，标准版 pymupdf 不能打开 Word 文件，会被当"无法打开"跳过，Word 格式 SI 实际永远配不上 | 对 `.docx` 用 python-docx 读首页文字，`.doc` 明确报告不支持 | `adapters.pdf_text`、`services.si_pairing` |
| `test_performance_numeric_fields_validated` | 新发现：`extract_performance` 不校验数值列，LLM 返回 `"~80"`、`"1.5 V"` 等字符串直接写 CSV；`None` 与 `""` 混用 | 数值列强制转 number 或 null，转换失败进失败队列或保留原文到 `other_metrics`；`test_type` 受词表约束 | `services.performance` |
| `test_performance_rerun_is_idempotent_and_crash_safe` | 新发现：`--force` 先 `remove_rows_for` 再 `append_rows`，两步之间崩溃会永久丢这批论文的数据；CSV 曾被非法字节污染，靠 `errors="replace"` 绕过 | 删旧与写新在同一事务；写入前统一 UTF-8 校验；`row_id` 稳定 | `services.performance` |
| `test_recent_added_not_affected_by_rewrite` | 新发现：面板"最近新增"按文件 mtime 排序，重生成、改名、规范化会改 mtime，旧论文冒充"最近新增"；`added` 只有日期，同日打平 | 用可靠的入库时间（含时分秒或序号）排序，不用文件 mtime | `core.index`、`interfaces.api` |
| `test_inbox_clear_goes_to_trash_with_confirmation` | 新发现：面板"清理 inbox"无确认直接 `unlink`/`rmtree`；入库后按 state 自动删 inbox 里的 PDF 也是硬删 | 所有删除进回收区，批量删除需确认，可恢复 | `services.maintenance`、`interfaces.api` |
| `test_upload_filename_sanitized_and_no_overwrite` | 新发现：面板上传按原始文件名写 inbox，同名覆盖；主题名直接拼进 `topics/_digest_<名>.md`，含路径分隔符可写到目录外 | 文件名与主题名必须清洗为安全 slug，禁止路径穿越，已存在则不覆盖（或以 sha256 去重） | `services.ingest`、`services.topics` |
| `test_secrets_never_written_plaintext` | 新发现：面板可把 API key 明文写入 `scripts/.local_config.json`，并注入子进程环境变量 | 密钥只存系统凭据库，不写文件、不写日志、不出现在任务记录与错误信息里；旧明文文件由 `migrate` 提示用户迁移后删除 | `adapters.secrets` |
| `test_no_arbitrary_shell_execution_endpoint` | 新发现：面板"命令"页以 `shell=True` 执行任意输入，自然语言翻译结果也直接可执行 | API 与前端不提供任意命令执行端点；所有动作都是受限、有参数校验的服务调用 | `interfaces.api`、`interfaces.web` |
| `test_user_agent_contact_from_config` | 新发现：Crossref 请求头里硬编码联系邮箱（`batch_ingest` 为个人邮箱，`scan_new_papers` 为占位邮箱），两处不同，且进了源码 | 联系邮箱来自用户配置，缺失时使用不含个人信息的通用客户端名；代码与测试数据里不出现真实邮箱 | `adapters.crossref`、`adapters.openalex`、`adapters.unpaywall` |
| `test_keyword_index_counts_from_structured_lists` | 新发现：`build_keyword_index.sh` 用 `tr ',' '\n'` 切列表，既受逗号缺陷影响，又把"次数"相同的词排序不确定；关键词统计与 `KEYWORDS.md` 手工估算（面板数 `\n- `）不一致 | 关键词与表征方法统计来自索引，计数精确，次数相同按字典序稳定排序 | `services.exports`、`core.index` |
| `test_dedupe_title_normalization` | 新发现：除 `batch_ingest` 外的标题查重只转小写，不做标点、Unicode、HTML 标签归一；`O(n²)` 两两比较在库增长后很慢 | 标题归一化与相似度集中到 `core.textsim`；全库查重用分桶或倒排预筛，保证 0.90 阈值语义不变 | `core.textsim`、`services.dedupe` |
