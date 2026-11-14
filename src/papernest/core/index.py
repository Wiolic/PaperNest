"""SQLite 索引（含 FTS5），可随时删除重建（DATA_MODEL 第 7 节）。

同步以笔记文件的 size + mtime 为快速判据，变了再比内容哈希，哈希也变才重新解析。
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import os
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.library import Library
from papernest.core.models import CITEKEY_RE, Note, PaperType, PerformanceRow, Status, normalize_doi
from papernest.core.note_io import read_note
from papernest.core.vocab import Vocab

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE papers(
  citekey TEXT PRIMARY KEY, title TEXT, year INT, journal TEXT, journal_norm TEXT, doi TEXT,
  volume TEXT, issue TEXT, pages TEXT, entry_type TEXT, type TEXT, methods TEXT, system TEXT,
  status TEXT, rating INT, added TEXT, has_pdf INT, si_count INT, is_top_journal INT,
  note_size INT, note_mtime REAL, note_hash TEXT);
CREATE INDEX papers_doi ON papers(doi);
CREATE INDEX papers_year ON papers(year);
CREATE INDEX papers_journal ON papers(journal_norm);
CREATE TABLE paper_authors(citekey TEXT, position INT, name TEXT);
CREATE TABLE paper_tags(citekey TEXT, tag TEXT);
CREATE INDEX paper_tags_tag ON paper_tags(tag);
CREATE INDEX paper_tags_ck ON paper_tags(citekey);
CREATE TABLE paper_keywords(citekey TEXT, keyword TEXT);
CREATE INDEX paper_keywords_ck ON paper_keywords(citekey);
CREATE TABLE paper_characterization(citekey TEXT, method TEXT, mapped INT);
CREATE INDEX paper_char_ck ON paper_characterization(citekey);
CREATE TABLE paper_related(citekey TEXT, related_citekey TEXT);
CREATE INDEX paper_related_ck ON paper_related(citekey);
CREATE TABLE sections(citekey TEXT, section_id TEXT, content TEXT);
CREATE INDEX sections_ck ON sections(citekey);
CREATE VIRTUAL TABLE notes_fts USING fts5(
  citekey UNINDEXED, title, authors, keywords, body, tokenize='unicode61');
CREATE TABLE fulltext_state(citekey TEXT PRIMARY KEY, size INT, mtime REAL);
CREATE VIRTUAL TABLE fulltext_fts USING fts5(citekey UNINDEXED, text, tokenize='unicode61');
CREATE TABLE performance(
  row_id TEXT PRIMARY KEY, citekey TEXT, test_type TEXT, reaction TEXT, electrolyte TEXT,
  temperature_C REAL, catalyst_loading_mg_cm2 REAL, current_density_ref_mA_cm2 REAL,
  overpotential_mV REAL, cell_voltage_V REAL, tafel_slope_mV_dec REAL,
  stability_duration_h REAL, degradation_rate REAL, other_metrics TEXT, source_location TEXT);
CREATE TABLE index_errors(citekey TEXT PRIMARY KEY, error TEXT, note_size INT, note_mtime REAL,
  note_hash TEXT);
"""

_CHILD_TABLES = (
    "paper_authors",
    "paper_tags",
    "paper_keywords",
    "paper_characterization",
    "paper_related",
    "sections",
)
_PERF_COLS = tuple(PerformanceRow.model_fields)
_CJK_RE = re.compile(r"([㐀-䶿一-鿿぀-ヿ가-힯])")
_PAPERS_MAIN_RE = re.compile(r"^([A-Za-z0-9-]+)\.[a-z0-9]+$")
_PAPERS_SI_RE = re.compile(r"^([A-Za-z0-9-]+)_SI\d*\.[a-z0-9]+$")


def _fts_text(s: str) -> str:
    """unicode61 把一串汉字当一个词；入库与查询两侧都按字拆开，使子串可检索。"""
    return _CJK_RE.sub(r" \1 ", s)


def _fts_query(text: str) -> str | None:
    """把用户输入转成 FTS5 查询：每个空白分隔的词一个短语，AND 连接，无语法错误。"""
    phrases = []
    for tok in text.split():
        tok = _fts_text(tok).replace('"', '""').strip()
        if tok:
            phrases.append(f'"{tok}"')
    return " ".join(phrases) or None


# ---- 对外的数据结构 ----


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndexError_(_Model):  # noqa: N801  规格给定的名字
    citekey: str
    error: str


class SyncReport(_Model):
    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    errors: list[IndexError_] = Field(default_factory=list)
    unchanged: int = 0


class PaperRow(_Model):
    citekey: str
    title: str
    authors: list[str]
    year: int | None
    journal: str | None
    doi: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    entry_type: str
    type: str | None
    tags: list[str]
    keywords: list[str]
    methods: str
    characterization: list[str]
    characterization_unmapped: list[str]
    system: str
    status: str
    rating: int | None
    related: list[str]
    added: str
    has_pdf: bool
    si_count: int
    is_top_journal: bool


SortKey = Literal["added_desc", "year_desc", "title", "relevance"]


class SearchQuery(_Model):
    text: str | None = None
    include_fulltext: bool = False
    tags_any: list[str] = Field(default_factory=list)
    tags_all: list[str] = Field(default_factory=list)
    journals: list[str] = Field(default_factory=list)
    top_journals_only: bool = False
    year_from: int | None = None
    year_to: int | None = None
    types: list[PaperType] = Field(default_factory=list)
    status: list[Status] = Field(default_factory=list)
    has_pdf: bool | None = None
    sort: SortKey = "added_desc"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1)


class SearchResult(_Model):
    total: int
    library_total: int
    items: list[PaperRow]


class FacetCount(_Model):
    value: str | int
    count: int


class Facets(_Model):
    tags: list[FacetCount]
    journals: list[FacetCount]
    years: list[FacetCount]
    types: list[FacetCount]
    status: list[FacetCount]


# ---- 内部 ----


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_stat(path: Path) -> tuple[int, float] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime


class Index:
    def __init__(self, library: Library) -> None:
        self.library = library
        self.db_path = library.state_dir / "index.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ---- 连接与建表 ----

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _delete_db_files(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            with contextlib.suppress(OSError):
                Path(str(self.db_path) + suffix).unlink()

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None:
                return self._conn
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            for _ in range(2):
                conn = self._open_db()
                if conn is not None:
                    self._conn = conn
                    return conn
                self._delete_db_files()
            raise PaperNestError(ErrorCode.INTERNAL, f"无法创建索引库：{self.db_path}")

    def _open_db(self) -> sqlite3.Connection | None:
        """打开并校验 schema；损坏或版本不符返回 None（调用方删库重来）。"""
        conn = sqlite3.connect(
            self.db_path, timeout=30, isolation_level=None, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        try:
            version: str | None = None
            with contextlib.suppress(sqlite3.OperationalError):
                row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                version = row[0] if row else None
            if version == str(SCHEMA_VERSION):
                return conn
            if version is not None or self._has_tables(conn):
                conn.close()
                return None
            conn.executescript(_SCHEMA)
            conn.execute("INSERT INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            conn.execute("INSERT INTO meta VALUES('built_at', ?)", (datetime.now().isoformat(),))
            return conn
        except sqlite3.DatabaseError:
            conn.close()
            return None

    @staticmethod
    def _has_tables(conn: sqlite3.Connection) -> bool:
        return conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 0

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    # ---- 同步 ----

    def rebuild(self) -> SyncReport:
        with self._lock:
            self.close()
            self._delete_db_files()
            return self.sync()

    def _vocab_hash(self) -> str:
        h = hashlib.sha256()
        for name in ("tags.yaml", "journals.yaml", "characterization.yaml"):
            p = self.library.root / "vocab" / name
            h.update(name.encode())
            if p.is_file():
                h.update(p.read_bytes())
        return h.hexdigest()

    def _papers_listing(self) -> tuple[dict[str, bool], dict[str, int]]:
        """一次目录遍历得出每个 citekey 是否有主文件、SI 个数（匹配规则与 Library 一致）。"""
        has_main: dict[str, bool] = {}
        si: dict[str, int] = {}
        d = self.library.papers_dir
        if d.is_dir():
            with os.scandir(d) as it:
                for e in it:
                    if not e.is_file():
                        continue
                    m = _PAPERS_SI_RE.match(e.name)
                    if m:
                        si[m.group(1)] = si.get(m.group(1), 0) + 1
                        continue
                    m = _PAPERS_MAIN_RE.match(e.name)
                    if m:
                        has_main[m.group(1)] = True
        return has_main, si

    def sync(self) -> SyncReport:
        with self._lock:
            conn = self._connect()
            report = SyncReport()
            vocab = Vocab.load(self.library.root / "vocab")
            vocab_hash = self._vocab_hash()
            row = conn.execute("SELECT value FROM meta WHERE key='vocab_hash'").fetchone()
            vocab_changed = row is None or row[0] != vocab_hash
            has_main, si_count = self._papers_listing()
            sections_cfg = self.library.config.note.sections

            known: dict[str, tuple[int, float, str]] = {}
            for r in conn.execute("SELECT citekey, note_size, note_mtime, note_hash FROM papers"):
                known[r[0]] = (r[1], r[2], r[3])
            broken: dict[str, tuple[int, float, str]] = {}
            for r in conn.execute(
                "SELECT citekey, note_size, note_mtime, note_hash FROM index_errors"
            ):
                broken[r[0]] = (r[1], r[2], r[3])
            old_errors = {
                r[0]: r[1] for r in conn.execute("SELECT citekey, error FROM index_errors")
            }

            on_disk: dict[str, Path] = {}
            if self.library.notes_dir.is_dir():
                with os.scandir(self.library.notes_dir) as it:
                    for e in it:
                        if e.is_file() and e.name.endswith(".md") and not e.name.startswith("."):
                            on_disk[e.name[:-3]] = Path(e.path)

            with self._tx() as tx:
                for ck in sorted(set(known) | set(broken)):
                    if ck not in on_disk:
                        self._delete_paper(tx, ck)
                        tx.execute("DELETE FROM index_errors WHERE citekey=?", (ck,))
                        if ck in known:
                            report.removed.append(ck)

                for ck in sorted(on_disk):
                    path = on_disk[ck]
                    stat = _file_stat(path)
                    if stat is None:
                        continue
                    size, mtime = stat
                    prev = known.get(ck) or broken.get(ck)
                    if prev and not vocab_changed and prev[0] == size and prev[1] == mtime:
                        report.unchanged += 1
                        if ck in old_errors:
                            report.errors.append(IndexError_(citekey=ck, error=old_errors[ck]))
                        continue
                    try:
                        digest = _sha256(path.read_bytes())
                    except OSError as e:
                        self._record_error(tx, ck, str(e), size, mtime, "")
                        report.errors.append(IndexError_(citekey=ck, error=str(e)))
                        continue
                    if prev and not vocab_changed and prev[2] == digest:
                        # 只是 mtime 变了（如复制、touch），内容没变，不重新解析
                        table = "papers" if ck in known else "index_errors"
                        tx.execute(
                            f"UPDATE {table} SET note_size=?, note_mtime=? WHERE citekey=?",
                            (size, mtime, ck),
                        )
                        report.unchanged += 1
                        if ck in old_errors:
                            report.errors.append(IndexError_(citekey=ck, error=old_errors[ck]))
                        continue
                    try:
                        note = read_note(path, sections_cfg)
                    except PaperNestError as e:
                        if ck in known:
                            self._delete_paper(tx, ck)
                            report.removed.append(ck)
                        self._record_error(tx, ck, e.message, size, mtime, digest)
                        report.errors.append(IndexError_(citekey=ck, error=e.message))
                        continue
                    tx.execute("DELETE FROM index_errors WHERE citekey=?", (ck,))
                    existed = ck in known
                    if existed:
                        self._delete_paper(tx, ck)
                    self._insert_paper(tx, note, vocab, size, mtime, digest)
                    if existed:
                        report.updated.append(ck)
                    else:
                        report.added.append(ck)

                self._refresh_files(tx, has_main, si_count)
                self._sync_fulltext(tx, set(on_disk))
                self._sync_performance(tx)
                tx.execute(
                    "INSERT INTO meta VALUES('vocab_hash', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (vocab_hash,),
                )
            return report

    def _record_error(
        self, tx: sqlite3.Connection, ck: str, error: str, size: int, mtime: float, digest: str
    ) -> None:
        tx.execute(
            "INSERT OR REPLACE INTO index_errors VALUES(?,?,?,?,?)",
            (ck, error, size, mtime, digest),
        )

    def _delete_paper(self, tx: sqlite3.Connection, ck: str) -> None:
        row = tx.execute("SELECT rowid FROM papers WHERE citekey=?", (ck,)).fetchone()
        if row is not None:
            tx.execute("DELETE FROM notes_fts WHERE rowid=?", (row[0],))
        for t in _CHILD_TABLES:
            tx.execute(f"DELETE FROM {t} WHERE citekey=?", (ck,))
        tx.execute("DELETE FROM papers WHERE citekey=?", (ck,))

    def _insert_paper(
        self,
        tx: sqlite3.Connection,
        note: Note,
        vocab: Vocab,
        size: int,
        mtime: float,
        digest: str,
    ) -> None:
        p = note.paper
        ck = p.citekey
        journal_norm = vocab.journal_key(p.journal) if p.journal else None
        cur = tx.execute(
            "INSERT INTO papers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ck, p.title, p.year, p.journal, journal_norm, p.doi, p.volume, p.issue, p.pages,
                p.entry_type.value, p.type.value if p.type else None, p.methods, p.system,
                p.status.value, p.rating, p.added.isoformat(timespec="seconds"),
                0, 0, int(vocab.is_top_journal(p.journal)), size, mtime, digest,
            ),
        )  # fmt: skip
        rowid = cur.lastrowid
        tx.executemany(
            "INSERT INTO paper_authors VALUES(?,?,?)",
            [(ck, i, a) for i, a in enumerate(p.authors)],
        )
        tx.executemany(
            "INSERT INTO paper_tags VALUES(?,?)", [(ck, t) for t in dict.fromkeys(p.tags)]
        )
        tx.executemany(
            "INSERT INTO paper_keywords VALUES(?,?)", [(ck, k) for k in dict.fromkeys(p.keywords)]
        )
        chars = [(ck, m, 1) for m in dict.fromkeys(p.characterization)]
        for m in dict.fromkeys(p.characterization_unmapped):
            # 旧库遗留的 `unmapped:` 前缀不进索引
            m = m[len("unmapped:") :].strip() if m.lower().startswith("unmapped:") else m
            chars.append((ck, m, 0))
        tx.executemany("INSERT INTO paper_characterization VALUES(?,?,?)", chars)
        tx.executemany(
            "INSERT INTO paper_related VALUES(?,?)", [(ck, r) for r in dict.fromkeys(p.related)]
        )
        tx.executemany(
            "INSERT INTO sections VALUES(?,?,?)", [(ck, s.id, s.content) for s in note.sections]
        )
        tx.execute(
            "INSERT INTO notes_fts(rowid, citekey, title, authors, keywords, body) "
            "VALUES(?,?,?,?,?,?)",
            (
                rowid, ck, _fts_text(p.title), _fts_text(", ".join(p.authors)),
                _fts_text(", ".join(p.keywords)), _fts_text(note.body_markdown()),
            ),
        )  # fmt: skip

    def _refresh_files(
        self, tx: sqlite3.Connection, has_main: dict[str, bool], si_count: dict[str, int]
    ) -> None:
        """主文件与 SI 随时可能被增删，与笔记是否改动无关，每次同步都核对一遍。"""
        updates = []
        for ck, hp, sc in tx.execute("SELECT citekey, has_pdf, si_count FROM papers").fetchall():
            new_hp, new_sc = int(has_main.get(ck, False)), si_count.get(ck, 0)
            if (hp, sc) != (new_hp, new_sc):
                updates.append((new_hp, new_sc, ck))
        tx.executemany("UPDATE papers SET has_pdf=?, si_count=? WHERE citekey=?", updates)

    def _sync_fulltext(self, tx: sqlite3.Connection, note_keys: set[str]) -> None:
        text_dir = self.library.root / "text"
        on_disk: dict[str, tuple[Path, int, float]] = {}
        if text_dir.is_dir():
            with os.scandir(text_dir) as it:
                for e in it:
                    if e.is_file() and e.name.endswith(".txt"):
                        ck = e.name[:-4]
                        if ck in note_keys and CITEKEY_RE.fullmatch(ck):
                            st = e.stat()
                            on_disk[ck] = (Path(e.path), st.st_size, st.st_mtime)
        known = {r[0]: (r[1], r[2], r[3]) for r in tx.execute(
            "SELECT citekey, size, mtime, rowid FROM fulltext_state")}  # fmt: skip
        for ck, (_s, _m, rowid) in known.items():
            if ck not in on_disk:
                tx.execute("DELETE FROM fulltext_fts WHERE rowid=?", (rowid,))
                tx.execute("DELETE FROM fulltext_state WHERE citekey=?", (ck,))
        for ck, (path, size, mtime) in on_disk.items():
            old = known.get(ck)
            if old and old[0] == size and old[1] == mtime:
                continue
            if old:
                tx.execute("DELETE FROM fulltext_fts WHERE rowid=?", (old[2],))
                tx.execute("DELETE FROM fulltext_state WHERE citekey=?", (ck,))
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            cur = tx.execute("INSERT INTO fulltext_state VALUES(?,?,?)", (ck, size, mtime))
            tx.execute(
                "INSERT INTO fulltext_fts(rowid, citekey, text) VALUES(?,?,?)",
                (cur.lastrowid, ck, _fts_text(text)),
            )

    def _sync_performance(self, tx: sqlite3.Connection) -> None:
        path = self.library.root / "data" / "performance.csv"
        stat = _file_stat(path)
        sig = f"{stat[0]}:{stat[1]}" if stat else ""
        row = tx.execute("SELECT value FROM meta WHERE key='performance_sig'").fetchone()
        if row is not None and row[0] == sig:
            return
        tx.execute("DELETE FROM performance")
        if stat is not None:
            with path.open(encoding="utf-8-sig", newline="") as f:
                for raw in csv.DictReader(f):
                    try:
                        pr = PerformanceRow.model_validate(
                            {k: v for k, v in raw.items() if k in _PERF_COLS}
                        )
                    except ValidationError:
                        continue  # 坏行由 doctor 报告，不进索引
                    tx.execute(
                        f"INSERT OR REPLACE INTO performance({','.join(_PERF_COLS)}) "
                        f"VALUES({','.join('?' * len(_PERF_COLS))})",
                        [getattr(pr, c) for c in _PERF_COLS],
                    )
        tx.execute(
            "INSERT INTO meta VALUES('performance_sig', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (sig,),
        )

    # ---- 查询 ----

    def _load_rows(self, conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[PaperRow]:
        if not rows:
            return []
        cks = [r["citekey"] for r in rows]
        marks = ",".join("?" * len(cks))

        def group(sql: str) -> dict[str, list[Any]]:
            out: dict[str, list[Any]] = {}
            for r in conn.execute(sql.format(marks), cks):
                out.setdefault(r[0], []).append(r[1:])
            return out

        authors = group(
            "SELECT citekey, name FROM paper_authors WHERE citekey IN ({}) ORDER BY position"
        )
        tags = group("SELECT citekey, tag FROM paper_tags WHERE citekey IN ({}) ORDER BY rowid")
        kws = group(
            "SELECT citekey, keyword FROM paper_keywords WHERE citekey IN ({}) ORDER BY rowid"
        )
        chars = group(
            "SELECT citekey, method, mapped FROM paper_characterization "
            "WHERE citekey IN ({}) ORDER BY rowid"
        )
        rel = group(
            "SELECT citekey, related_citekey FROM paper_related "
            "WHERE citekey IN ({}) ORDER BY rowid"
        )
        out = []
        for r in rows:
            ck = r["citekey"]
            c = chars.get(ck, [])
            out.append(
                PaperRow(
                    citekey=ck, title=r["title"], authors=[a[0] for a in authors.get(ck, [])],
                    year=r["year"], journal=r["journal"], doi=r["doi"], volume=r["volume"],
                    issue=r["issue"], pages=r["pages"], entry_type=r["entry_type"],
                    type=r["type"], tags=[t[0] for t in tags.get(ck, [])],
                    keywords=[k[0] for k in kws.get(ck, [])], methods=r["methods"],
                    characterization=[m for m, mapped in c if mapped],
                    characterization_unmapped=[m for m, mapped in c if not mapped],
                    system=r["system"], status=r["status"], rating=r["rating"],
                    related=[x[0] for x in rel.get(ck, [])], added=r["added"],
                    has_pdf=bool(r["has_pdf"]), si_count=r["si_count"],
                    is_top_journal=bool(r["is_top_journal"]),
                )
            )  # fmt: skip
        return out

    def get(self, citekey: str) -> PaperRow | None:
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM papers WHERE citekey=?", (citekey,)).fetchone()
            return self._load_rows(conn, [row])[0] if row else None

    def search(self, query: SearchQuery) -> SearchResult:
        with self._lock:
            conn = self._connect()
            vocab = Vocab.load(self.library.root / "vocab")
            where: list[str] = []
            params: dict[str, Any] = {}
            ctes = ""
            fts = _fts_query(query.text) if query.text else None
            score_join = ""
            if query.text and query.text.strip():
                if fts is None:
                    where.append("0")
                else:
                    params["q"] = fts
                    hit_sql = (
                        "SELECT p.citekey AS citekey, f.score AS score FROM fts_hits f "
                        "JOIN papers p ON p.rowid = f.rid"
                    )
                    if query.include_fulltext:
                        hit_sql += (
                            " UNION ALL SELECT citekey, 0.0 FROM fulltext_fts "
                            "WHERE fulltext_fts MATCH :q"
                        )
                    # bm25() 只能在直接查询 FTS 表的语句里用，所以单独成一个 CTE
                    ctes = (
                        "WITH fts_hits AS MATERIALIZED "
                        "(SELECT rowid AS rid, bm25(notes_fts) AS score "
                        "FROM notes_fts WHERE notes_fts MATCH :q), "
                        f"hits AS (SELECT citekey, MIN(score) AS score FROM ({hit_sql}) "
                        "GROUP BY citekey) "
                    )
                    score_join = "JOIN hits ON hits.citekey = p.citekey"
            for i, tag in enumerate(query.tags_all):
                params[f"ta{i}"] = tag
                where.append(
                    "EXISTS (SELECT 1 FROM paper_tags t "
                    f"WHERE t.citekey=p.citekey AND t.tag=:ta{i})"
                )
            if query.tags_any:
                names = []
                for i, tag in enumerate(query.tags_any):
                    params[f"tn{i}"] = tag
                    names.append(f":tn{i}")
                where.append(
                    "EXISTS (SELECT 1 FROM paper_tags t WHERE t.citekey=p.citekey AND t.tag IN "
                    f"({','.join(names)}))"
                )
            if query.journals:
                keys = []
                for i, j in enumerate(query.journals):
                    params[f"j{i}"] = vocab.journal_key(j)
                    keys.append(f":j{i}")
                where.append(f"p.journal_norm IN ({','.join(keys)})")
            if query.top_journals_only:
                where.append("p.is_top_journal = 1")
            if query.year_from is not None:
                params["yf"] = query.year_from
                where.append("p.year >= :yf")
            if query.year_to is not None:
                params["yt"] = query.year_to
                where.append("p.year <= :yt")
            if query.types:
                names = []
                for i, t in enumerate(query.types):
                    params[f"ty{i}"] = t.value
                    names.append(f":ty{i}")
                where.append(f"p.type IN ({','.join(names)})")
            if query.status:
                names = []
                for i, s in enumerate(query.status):
                    params[f"st{i}"] = s.value
                    names.append(f":st{i}")
                where.append(f"p.status IN ({','.join(names)})")
            if query.has_pdf is not None:
                params["hp"] = int(query.has_pdf)
                where.append("p.has_pdf = :hp")

            sort = query.sort
            if sort == "relevance" and not score_join:
                sort = "added_desc"
            order = {
                "added_desc": "p.added DESC, p.citekey",
                "year_desc": "p.year IS NULL, p.year DESC, p.citekey",
                "title": "p.title COLLATE NOCASE, p.citekey",
                "relevance": "hits.score, p.citekey",
            }[sort]
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            base = f"FROM papers p {score_join}{clause}"
            total = conn.execute(f"{ctes}SELECT count(*) {base}", params).fetchone()[0]
            library_total = conn.execute("SELECT count(*) FROM papers").fetchone()[0]
            params["lim"], params["off"] = query.limit, query.offset
            rows = conn.execute(
                f"{ctes}SELECT p.* {base} ORDER BY {order} LIMIT :lim OFFSET :off", params
            ).fetchall()
            return SearchResult(
                total=total, library_total=library_total, items=self._load_rows(conn, rows)
            )

    def _counts(self, sql: str) -> list[FacetCount]:
        conn = self._connect()
        return [FacetCount(value=r[0], count=r[1]) for r in conn.execute(sql)]

    def facets(self) -> Facets:
        with self._lock:
            return Facets(
                tags=self._counts(
                    "SELECT tag, count(*) c FROM paper_tags GROUP BY tag ORDER BY c DESC, tag"
                ),
                journals=self._counts(
                    "SELECT MIN(journal), count(*) c FROM papers WHERE journal_norm IS NOT NULL "
                    "GROUP BY journal_norm ORDER BY c DESC, MIN(journal)"
                ),
                years=self._counts(
                    "SELECT year, count(*) c FROM papers WHERE year IS NOT NULL "
                    "GROUP BY year ORDER BY year DESC"
                ),
                types=self._counts(
                    "SELECT type, count(*) c FROM papers WHERE type IS NOT NULL "
                    "GROUP BY type ORDER BY c DESC, type"
                ),
                status=self._counts(
                    "SELECT status, count(*) c FROM papers GROUP BY status ORDER BY c DESC, status"
                ),
            )

    def keyword_counts(self) -> list[FacetCount]:
        """关键词计数：次数降序，次数相同按字典序，结果稳定。"""
        with self._lock:
            return self._counts(
                "SELECT keyword, count(*) c FROM paper_keywords GROUP BY keyword "
                "ORDER BY c DESC, keyword"
            )

    def characterization_counts(self, mapped: bool | None = None) -> list[FacetCount]:
        with self._lock:
            where = "" if mapped is None else f" WHERE mapped={int(mapped)}"
            return self._counts(
                "SELECT method, count(*) c FROM paper_characterization"
                f"{where} GROUP BY method ORDER BY c DESC, method"
            )

    def find_by_doi(self, doi: str) -> list[str]:
        norm = normalize_doi(doi)
        if not norm:
            return []
        with self._lock:
            rows = self._connect().execute(
                "SELECT citekey FROM papers WHERE doi=? ORDER BY citekey", (norm,)
            )
            return [r[0] for r in rows]

    def all_titles(self) -> list[tuple[str, str]]:
        with self._lock:
            rows = self._connect().execute("SELECT citekey, title FROM papers ORDER BY citekey")
            return [(r[0], r[1]) for r in rows]

    def errors(self) -> list[IndexError_]:
        with self._lock:
            rows = self._connect().execute(
                "SELECT citekey, error FROM index_errors ORDER BY citekey"
            )
            return [IndexError_(citekey=r[0], error=r[1]) for r in rows]

    def performance_rows(self, citekey: str | None = None) -> list[PerformanceRow]:
        with self._lock:
            conn = self._connect()
            if citekey is None:
                rows = conn.execute("SELECT * FROM performance ORDER BY row_id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM performance WHERE citekey=? ORDER BY row_id", (citekey,)
                ).fetchall()
            return [PerformanceRow.model_validate(dict(r)) for r in rows]
