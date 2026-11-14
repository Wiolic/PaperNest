# 阶段 2 规格：核心层

执行档位：Sonnet（测试样例库可派 Haiku 子代理生成）。前置阅读：`docs/DATA_MODEL.md` 全文、`docs/ARCHITECTURE.md` 第 4、6、9 节、`docs/LEGACY_MAP.md` 第 3、5 节。

目标：`papernest.core` 全部模块 + `services.doctor` + 最小的只读 CLI。完成后可以对一个符合 v1 格式的库做打开、校验、索引、检索。

核心层不触网、不调 LLM。所有公开函数带类型标注。

## 1. core/models.py

pydantic v2 模型，全部 `model_config = ConfigDict(extra="forbid")`。

- `PaperType`、`Status`、`EntryType`：`StrEnum`，取值见 DATA_MODEL 3.2。
- `Paper`：DATA_MODEL 3.2 的全部字段，字段声明顺序即写出顺序。校验器：
  - `citekey` 匹配 DATA_MODEL 第 4 节正则；
  - `doi` 归一化：去掉 `https://doi.org/`、`doi:` 前缀，转小写，去首尾空格；空串 → None；
  - `title` 去首尾空格、内部换行替换为空格、非空；
  - `rating` 1–5；`year` 1800–2100。
- `Section`：`id: str | None`、`heading: str`、`content: str`。`id` 为 None 表示配置里没有的自定义小节。
- `Note`：`paper: Paper`、`sections: list[Section]`。方法 `section(id) -> str`、`body_markdown() -> str`。
- `Attachment`：`path: Path`、`kind: Literal["main","si"]`。
- `PerformanceRow`：DATA_MODEL 第 6 节的列；数值列 `float | None`。
- `LibraryConfig`：`papernest.toml` 的全部段，带 DATA_MODEL 第 2 节所示默认值。

## 2. core/note_io.py

```python
def parse_note(text: str, sections_cfg: list[SectionCfg]) -> Note
def dump_note(note: Note) -> str
def read_note(path: Path, sections_cfg) -> Note        # citekey 与文件名不符时抛 note_invalid
def write_note(path: Path, note: Note) -> None         # 经 library.atomic_write
```

- 解析：以首行 `---` 开始，到下一个独占一行的 `---` 结束为 frontmatter，用 `yaml.safe_load`；其余为正文。正文按 `^## ` 切分小节，标题与配置的 `heading` 完全相等的赋对应 `id`，其余 `id=None` 并保持原顺序排在后面。第一个 `## ` 之前若有非空白内容，作为 `heading=""` 的前置小节保留。
- 输出：遵守 DATA_MODEL 3.3。实现一个自定义 `yaml.SafeDumper` 子类 + 手工逐键输出（每个键一行）。
- 不变量（测试强制）：`parse_note(dump_note(n)) == n`；`dump_note(parse_note(dump_note(n))) == dump_note(n)`。
- 读入时接受 CRLF 与 BOM，写出时一律 LF 无 BOM。

## 3. core/library.py

```python
class Library:
    root: Path
    config: LibraryConfig
    @classmethod
    def open(cls, root: Path) -> "Library"        # 无 papernest.toml → library_not_found；版本过新 → library_format_too_new
    @classmethod
    def create(cls, root: Path, name: str) -> "Library"   # 建目录骨架、默认配置、空词表
    def note_path(self, citekey) -> Path
    def text_path(self, citekey) -> Path
    def main_file(self, citekey) -> Path | None   # papers/<ck>.<ext>，精确匹配
    def si_files(self, citekey) -> list[Path]     # papers/<ck>_SI.<ext>、_SI2 …，按序号排序
    def files_of(self, citekey) -> list[Path]     # 以上全部存在的文件
    def list_citekeys(self) -> list[str]          # 以 notes/*.md 为准，排序
    def write_lock(self, timeout=30) -> ContextManager     # filelock，超时抛 locked
    def atomic_write(self, path: Path, data: str | bytes) -> None
    def trash(self, paths: list[Path], operation: str) -> Path   # 移入 .papernest/trash/<时间戳>-<operation>/，保留相对路径，返回回收目录
    def restore(self, trash_dir: Path) -> list[Path]
```

- `main_file` 与 `si_files` 的匹配用正则 `^<re.escape(ck)>\.[a-z0-9]+$` 与 `^<re.escape(ck)>_SI(\d*)\.[a-z0-9]+$`，对 `papers/` 目录列表过滤。`X-2.pdf` 绝不能匹配 `X`。
- `atomic_write`：同目录写 `.<name>.tmp` → flush + fsync → `os.replace`。文本以 `newline="\n"`、`encoding="utf-8"` 写。
- 格式迁移框架：`MIGRATIONS: dict[int, Callable[[Library], None]]`（v1 时为空）与 `upgrade()`，含备份逻辑（ARCHITECTURE 第 10 节）。

## 4. core/vocab.py

```python
class Vocab:
    @classmethod
    def load(cls, vocab_dir: Path) -> "Vocab"
    def save(self) -> None
    def normalize_tag(self, raw) -> tuple[str, bool]            # (规范名, 是否在表内)
    def journal(self, name) -> JournalEntry | None              # 按归一化名或别名查
    def journal_abbr(self, name) -> str | None
    def is_top_journal(self, name) -> bool
    def normalize_characterization(self, raw) -> tuple[str, bool]
    def add_tag(self, name, unreviewed=True) -> None
    def add_journal(self, name, abbr, unreviewed=True) -> None  # abbr 已被别的期刊占用时抛错
```

- 期刊名归一化：`casefold`、去首尾空格、去开头的 `the `、连续空白压成一个空格、`&` 视同 `and`。
- 表征方法归一化：先剥离 `prefixes` 中的前缀（不区分大小写，前缀后可跟空格或连字符），在 `name` 与 `aliases` 里不区分大小写查找，命中则返回 `"<前缀> <规范名>"`；未命中返回原文与 False。

## 5. core/textsim.py

```python
def normalize_title(s: str) -> str      # casefold，去标点，压空白
def title_similarity(a: str, b: str) -> float     # rapidfuzz.fuzz.ratio(normalize(a), normalize(b)) / 100
def normalize_filename(stem: str) -> str          # 去 SI 标记词后再归一化
def find_similar_titles(items: list[tuple[str, str]], threshold: float) -> list[tuple[str, str, float]]
```

- `find_similar_titles` 用 `rapidfuzz.process.cdist` 或带 `score_cutoff` 的两两比较，1 万条规模须在数秒内完成。
- SI 标记词表与正则原样取自 `LEGACY_MAP.md` 第 3 节。

## 6. core/citekey.py

```python
def validate(citekey: str) -> None
def condense_words(words: list[str], preserve: set[str]) -> str     # 规范大小写后连字符连接
def build(year: int | None, journal_abbr: str | None, condensed_title: str) -> str
def uniquify(base: str, existing: Collection[str]) -> str           # 追加 -2、-3
```

`uniquify` 的比较不区分大小写（Windows 文件系统大小写不敏感）。

## 7. core/index.py

```python
class Index:
    def __init__(self, library: Library)
    def sync(self) -> SyncReport            # added / updated / removed / errors
    def rebuild(self) -> SyncReport
    def get(self, citekey) -> PaperRow | None
    def search(self, query: SearchQuery) -> SearchResult
    def facets(self) -> Facets              # tags、journals、years、types、status 各自的计数
    def find_by_doi(self, doi) -> list[str]
    def all_titles(self) -> list[tuple[str, str]]
    def errors(self) -> list[IndexError_]
```

- `SearchQuery`：`text`（FTS，匹配标题、作者、关键词、正文）、`tags_any`、`tags_all`、`journals`、`top_journals_only`、`year_from`、`year_to`、`types`、`status`、`has_pdf`、`sort`（`added_desc` 默认 | `year_desc` | `title` | `relevance`）、`offset`、`limit`。
- `SearchResult`：`total`、`library_total`、`items`。
- 表结构见 DATA_MODEL 第 7 节。`schema_version` 不符即删库重建。
- FTS 分词器用 `unicode61`；中文按字检索可接受。用户输入的查询串要转义成 FTS 短语，避免语法错误。

## 8. core/state.py

建表（DATA_MODEL 第 8 节）与最薄的一层访问函数：`ledger_get/put`、`watermark_get/put`、`review_add/list/resolve`、`job_*`、`wanted_*`、`usage_add`。本阶段只需建表和 ledger、watermark、review 三组的读写及测试；`job_*`、`wanted_*` 留接口，阶段 5、8 实现。

## 9. services/doctor.py

```python
def check(ctx) -> DoctorReport
```

检查项（每项返回 `code`、`severity`（error|warning|info）、涉及的 citekey 列表、说明）：

1. `note_invalid`：解析或校验失败的笔记。
2. `missing_main_file`：有笔记无主文件。
3. `orphan_file`：`papers/` 或 `text/` 里不属于任何 citekey 的文件。
4. `si_mismatch`：`si_files` 列的文件不存在，或存在 `_SI` 文件未被列入。
5. `missing_text`：有主文件无 `text/`。
6. `duplicate_doi`：同一 DOI 多个 citekey。
7. `similar_titles`：标题相似度 ≥ 配置阈值的成对条目。
8. `tag_not_in_vocab`、`journal_not_in_vocab`、`unreviewed_vocab`。
9. `characterization_unmapped`：统计未归一化的写法及次数。
10. `dangling_related`：`related` 指向不存在的 citekey。
11. `dangling_topic_ref`：`topics/*.md` 里 `[[x]]` 不存在。
12. `performance_orphan`：`performance.csv` 的 citekey 不存在。
13. `inbox_pending`：inbox 文件数（info）。

## 10. CLI（只读部分）

`papernest library init <路径> --name`、`library info`、`paper list`（映射 SearchQuery 的参数）、`paper show <citekey>`、`index rebuild`、`doctor`。全部支持 `--json` 与 `--library`。

`ServiceContext` 在 `services/context.py` 定义并由 CLI 构造；本阶段适配器字段全部为 None。

## 11. 测试

- `tests/fixtures/library_small/`：12 篇人工构造的笔记（内容虚构，不用真实论文），必须覆盖：标题含 `: `；标题含引号与 `#`；关键词含逗号（`"Cu(111), Ag"`）；年份 null（citekey 以 `unknown-` 开头）；DOI null；一对 `X` 与 `X-2`；一篇带两个 SI（pdf + docx）；一篇有用户自定义的额外小节；一篇全部可空字段为空；中文作者名；一对标题相似度 > 0.9 的重复；一篇 tag 不在词表。`papers/` 里放几个字节的占位文件即可。
- `LEGACY_MAP.md` 第 5 节中归属 core 或 doctor 的每条回归用例，建同名测试。
- 性质测试：对样例库每篇笔记断言 note_io 的两条不变量。
- 并发测试：两个线程同时在写锁内改同一文件，结果不丢更新。
- 覆盖率：`core/` ≥ 90%。

## 12. 验收清单

```
uv run pytest --cov=papernest.core --cov-fail-under=90    通过
uv run ruff check . && uv run pyright                       无报错
uv run papernest --library tests/fixtures/library_small doctor --json    输出合法 JSON，且恰好报出样例库里预埋的问题
uv run papernest --library tests/fixtures/library_small paper list --text <某关键词> --json    命中预期条目
```

预计需要 2–3 个会话。建议切分：① models + note_io + library；② vocab + textsim + citekey + index；③ state + doctor + CLI。每段结束都按 `CLAUDE.md` 收尾。
