# 进度日志

最新的记录写在最上面。

## 当前状态

- **已完成**：阶段 0（规格奠基）、阶段 1（工程脚手架）、阶段 2 第一、二段（models、note_io、library、vocab、textsim、citekey、index）
- **下一步**：阶段 2 第三段（state + services.doctor + 只读 CLI + 验收清单），执行档 Sonnet，规格 `docs/specs/02-core.md` 第 8–10、12 节
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

阶段 2 第一段（models / note_io / library）中规格没写清、按最保守做法处理的地方：

11. **新增 3 个 `ErrorCode`**：`LIBRARY_EXISTS`（`create` 遇到已有库）、`CONFIG_INVALID`（`papernest.toml` 解析或校验失败）、`FILE_EXISTS`（`restore` 目标已存在）。规格的错误码表没有合适项；`interfaces/api/app.py` 的 HTTP 映射尚未登记它们（目前落到 500），需架构档定状态码并补进 ARCHITECTURE 第 7 节。
12. **`note_io` 没有写 `SafeDumper` 子类**：规格写"自定义 SafeDumper + 手工逐键输出"。实际是手工逐键输出，标量先按保守规则判风险（含 `: , # [ ] { }"`、首字符特殊、控制字符等一律双引号），否则用 `yaml.safe_load` 试读，读回不等就加引号。效果等价且更易验证，故未引入 Dumper 子类。
13. **`parse_note` 的小节规则**：配置内的小节按配置顺序排在前面（排在前置内容之后），未知小节保持原序跟在后面；文件里缺的配置小节**不**补空节（`Note.section(id)` 对缺失返回 `""`）；同一标题重复出现时，只有第一个带 `id`，其余作为未知小节保留。小节内容正文里若有以 `## ` 开头的行（如代码块里），会被当作新小节切开，往返时会改变结构——规格要求按 `^## ` 切分，没有跳过代码围栏，需架构档确认是否要处理。
14. **小节内容归一化**：`Section.content` 去掉首尾空白行、行尾空白只在纯空白行上去除，统一 LF。这是为了满足往返不变量。
15. **`Paper.year`、`rating` 用严格整数**（`"2024"` 字符串会被拒绝），其余字符串字段不做宽松转换（`volume: 12` 这种整数会校验失败）。手写笔记若写了裸数字，需要用户加引号；若希望宽松，需架构档定。`added` 去掉微秒，带时区的转本地 naive。
16. **`Library.open` 遇旧版本会自动 `upgrade()`**（带备份）；`v1` 下不会触发，测试用 monkeypatch 把 `FORMAT_VERSION` 调高验证。
17. **`main_file` 在同时存在多个扩展名时优先 `.pdf`，否则按文件名排序取第一个**。扩展名只认小写（规格正则）；Windows 文件系统不分大小写，不能在测试里同时建 `.PDF` 与 `.pdf`。
18. **`list_citekeys` 不校验文件名格式**（以 `notes/*.md` 为准），格式不合法的由 doctor 报告；但 `note_path/text_path/main_file/si_files/files_of` 对不合法 citekey 抛 `citekey_invalid`，同时挡住路径穿越。
19. **`trash` 对库外路径、`.papernest/` 内部文件、不存在的路径一律拒绝，且校验全部通过后才开始移动**；`restore` 目标有任一已存在则整体拒绝。
20. **`atomic_write` 作为模块级函数放在 `library.py`**（`Library.atomic_write` 只是转调），因为 `note_io.write_note(path, note)` 签名里没有 Library，而 `library` 不能反向 import `note_io`。`os.replace` 遇 `PermissionError`（Windows 杀毒/索引器占用）会重试 8 次。
21. **`tests/__init__.py` 与 `tests/unit/__init__.py`** 为让测试间共用 `make_paper` 而新增。
22. **样例库**目前含 `notes/`（12 篇）、`papers/`（占位文件）、`papernest.toml`，以及 `Library.create` 生成的空词表、`profile.md`、`data/performance.csv` 表头。词表是空的，所以每篇的 tag 在后续 doctor 里都会"不在词表"；第二段做 vocab 时需要填入词表并设计"恰好一篇 tag 不在表"（预埋的是 `2023-Joule-Solar-Fuel-Cell` 的 `未收录标签`）。`text/` 目录为空（git 不跟踪空目录），第三段 doctor 的 `missing_text` 预期相应处理。样例里预埋：标题含 `: `（Nickel、Ruthenium）、含引号与 `#`、关键词含逗号、两篇 `unknown-`、DOI 为空、`X`/`X-2` 且标题相似度 > 0.9、一篇两个 SI、一篇自定义小节、一篇全空、中文作者。

阶段 2 第二段（vocab / textsim / citekey / index）中规格没写清、按最保守做法处理的地方：

23. **新增 `ErrorCode.VOCAB_CONFLICT`**（`add_journal` 缩写被占或同一期刊换缩写）。词表文件解析失败复用 `CONFIG_INVALID`。HTTP 状态码需架构档补进 ARCHITECTURE 第 7 节（目前落到 500）。
24. **期刊表查找键**：全名与别名优先，缩写作为最低优先级的补充键（`journal_abbr("JACS")` 也能命中）。`Vocab.journal_key()` 是新增公开方法：表内期刊取规范全名的归一化形式，使别名在索引与过滤里合并；`papers.journal_norm` 用它。`add_journal` 缩写只允许 `[A-Za-z0-9]+`（citekey 要用），占用检查不区分大小写；同名同缩写重复添加为空操作。
25. **表征方法归一化**：前缀匹配容忍 `in-situ`、`insitu`、`In Situ`（LEGACY 第 5 节新发现项）；只有前缀没有技术名时不当作前缀；读入时顺手去掉旧库遗留的 `unmapped:` 前缀；中文前缀"原位/工况下/非原位"（LEGACY R07）规格未要求，未做。
26. **词表类 `save()` 只写 tags/journals/characterization 三个文件**，不碰 `discovery.yaml`；输出为块式映射 + 行内标量列表，样例库词表即由它生成，测试断言往返字节不变。词表里出现未知键即报错（与笔记一致 extra=forbid）。
27. **textsim**：`normalize_title` 额外去 HTML 标签与实体、做 NFKC，标点一律视作空白；`normalize_filename` 切词用 `[\W_]+` 而非 LEGACY 的 `[^a-z0-9]+`（后者会把中文文件名切光）；缺失 DOI/标题占位集合（R05）放在 `textsim`，提供 `is_missing_doi/is_missing_title`。`models.normalize_doi` 不处理占位值（"N/A" 仍是字符串），迁移与入库层需先过 `is_missing_doi`。归一化后为空的标题不参与相似度（返回 0 / 不进配对）。
28. **`find_similar_titles` 未用 `cdist`**：环境没有 numpy，而 `cdist` 依赖它；改为按长度排序 + 长度窗口 + `process.extract(score_cutoff)`，结果与暴力比较一致（有对拍测试）。1 万条约 2–3 秒。
29. **citekey**：`build` 的期刊缩写为空时按 DATA_MODEL 写 `unknown`（LEGACY R03 写的是 `Journal`，两者冲突，取 DATA_MODEL）；`condense_words` 的 `preserve` 缺省为空，另提供 `DEFAULT_PRESERVE`（取自 R03 点名的元素与缩写）供调用方选用，是否写死不由 core 决定；词内连字符与标点当作分隔。
30. **index 的小决定**：
    - `SearchQuery` 新增 `include_fulltext`（默认 False，text 只搜笔记 FTS）；规格提到"全文可在配置中关闭"，但 `LibraryConfig` 没有该开关，故 `text/` 一律索引。
    - FTS 对汉字入库与查询两侧都按字拆开，使中文子串可检索；英文按词、多词 AND。
    - 额外的内部表：`fulltext_state`（全文文件 size/mtime）、`index_errors` 带 size/mtime/hash（坏文件不重复解析）。`meta` 另存 `vocab_hash`、`performance_sig`。词表文件变了会让下次 `sync` 重新解析全部笔记（派生列如顶刊标记依赖词表），这些笔记计入 `updated`。
    - `has_pdf/si_count` 每次 `sync` 都按 `papers/` 目录核对一遍（一次遍历），不依赖笔记是否改动；匹配规则与 `Library.main_file/si_files` 一致，有对拍测试。
    - 解析失败的笔记若此前在索引里，会从索引移除并计入 `removed` 与 `errors`。
    - 新增 `Index.keyword_counts()`、`characterization_counts()`、`performance_rows()`、`close()`；`performance.csv` 在 `sync` 时载入 `performance` 表，非法行跳过（由 doctor 报告）。
    - `facets()` 统计全库，不随查询过滤；`journals` 按 `journal_norm` 合并，显示名取最小的原写法。`tags` 存笔记里的原写法（不经词表归一，才能看出"不在词表"）。
    - `Index` 自己不持有 `Vocab`，每次 `sync/search` 现读词表文件；连接带 `RLock`，可被 API 线程池共用。
31. 样例库词表：tags 6 项（含 `单原子` 的别名 `单原子催化`）、期刊 9 项（样例用到的 8 个，外加 Angewandte 以覆盖 `ACIE` 别名用例）、表征方法 9 项（XAS/XANES/EXAFS/STM/Raman/XRD/XPS/TEM/AFM）。`未收录标签` 是唯一不在词表里的 tag；`wacky probe` 是唯一未映射的表征写法。样例里 `2021-Science-Layered-Oxide-Transport` 没有 papers 占位文件（第一段遗留），所以 `has_pdf=False` 共两篇（另一篇是 `unknown-unknown-Sparse-Record`）；第三段 doctor 的 `missing_main_file` 预期应是这两篇。

## 相对 `PLAN.md` 的调整

- 卷期页的 Crossref 补齐从"迁移时做"改为阶段 4 的独立命令 `papernest paper enrich`，因为迁移工具不触网，这样迁移结果可离线复现和校验。
- PDF 文本抽取从 PyMuPDF 换成 pypdfium2：PyMuPDF 是 AGPL 许可，不适合随 MIT 软件一起分发。

## 记录

### 阶段 2 第二段 — vocab + textsim + citekey + index（执行档）

产出：`core/vocab.py`、`core/textsim.py`、`core/citekey.py`、`core/index.py`、样例库词表三份，以及四份单元测试；`errors.py` 增加 `VOCAB_CONFLICT`。models、note_io、library 未改。pytest 236 项全过，`core/` 覆盖率 97.7%，ruff、ruff format、pyright、`test_layering` 通过。`find_similar_titles` 1 万条性能测试与 `sync` 增量测试（改一个文件只重解析一个）均已建。回归用例同名测试：`test_journal_abbr_canonical_mapping`、`test_top_journals_match_normalizes_journal_names`、`test_characterization_prefix_variants_normalized`、`test_unmapped_prefix_not_in_frontmatter`（vocab 与 index 两侧）、`test_citekey_collision_case_insensitive`、`test_dedupe_title_normalization`、`test_crossref_title_html_tags_stripped_on_ingest`（textsim 部分）、`test_missing_doi_placeholders_single_definition`（定义部分）、`test_title_dedupe_does_not_bleed_across_bib_entries`、`test_recent_added_not_affected_by_rewrite`、`test_keyword_index_counts_from_structured_lists`。

踩坑：

- 环境没有 numpy，`rapidfuzz.process.cdist` 不可用，见待决定第 28 条。
- SQLite 的 `bm25()` 只能在直接查询 FTS 表的语句里用，放进带 JOIN 的子查询会报"unable to use function bm25"；要用 `AS MATERIALIZED` 的 CTE 单独取分。
- 仓库有保存即格式化的钩子，Write 之后文件内容会被 ruff 改写，再 Edit 前要重新读。
- CI 跑 Python 3.11：不要用 PEP 695 的 `def f[T]()` 泛型语法。

### 阶段 2 第一段 — models + note_io + library（执行档）

产出：`core/models.py`、`core/note_io.py`、`core/library.py`、样例库 `tests/fixtures/library_small/`、`tests/conftest.py` 与三份单元测试。`core/` 覆盖率 97%；pytest 128 项、ruff、pyright、`test_layering` 全过。回归用例已建同名测试：`test_list_fields_with_commas_roundtrip`、`test_frontmatter_values_with_colon_roundtrip`、`test_empty_field_does_not_swallow_newline`、`test_notes_written_with_lf_only`、`test_author_names_not_split_by_last_word`、`test_concurrent_writes_no_lost_update`、`test_state_write_is_atomic`（库层原子写部分，`state` 部分留第三段）。

踩坑：

- 用 bash 的 heredoc 写含引号与反斜杠的测试文件会失败或被转义，改用 Write 工具。
- Windows 文件系统大小写不敏感，`X.PDF` 与 `X.pdf` 是同一个文件，测试不能依赖它们并存。
- 样例库由一次性脚本经 `dump_note` 生成（脚本不入库），所以样例笔记本身就是规范输出，测试断言 `dump(parse(文件)) == 文件`。


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
