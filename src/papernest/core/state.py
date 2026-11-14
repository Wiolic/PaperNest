"""state.db：不可重建的运行状态（DATA_MODEL 第 8 节）。

本阶段实现建表与 ledger、watermark、review 三组读写；job_*、wanted_*、usage_add 只留接口。
SQLite 事务保证每次写入"要么旧版要么新版"（LEGACY：test_state_write_is_atomic）。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal, NoReturn

from pydantic import BaseModel, ConfigDict

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.library import Library

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS jobs(
    id TEXT PRIMARY KEY, kind TEXT, params_json TEXT, status TEXT,
    progress_done INTEGER, progress_total INTEGER, message TEXT,
    result_json TEXT, error_json TEXT, created_at TEXT, started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS job_logs(job_id TEXT, seq INTEGER, at TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS review_items(
    id TEXT PRIMARY KEY, kind TEXT, job_id TEXT, payload_json TEXT, status TEXT,
    decision_json TEXT, decided_by TEXT, created_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS ingest_ledger(
    sha256 TEXT PRIMARY KEY, original_name TEXT, outcome TEXT, citekey TEXT,
    detail TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS scan_watermarks(
    field TEXT PRIMARY KEY, last_scanned TEXT, history_json TEXT);
CREATE TABLE IF NOT EXISTS wanted(
    id TEXT PRIMARY KEY, doi TEXT, title TEXT, journal TEXT, year INTEGER, category TEXT,
    source_field TEXT, status TEXT, detail TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS llm_usage(
    at TEXT, job_id TEXT, tier TEXT, model TEXT,
    prompt_tokens INTEGER, completion_tokens INTEGER);
"""

LedgerOutcome = Literal["ingested", "duplicate", "skipped", "error", "pending_review"]
ReviewKind = Literal["duplicate", "doi_unverified", "si_pairing", "metadata_missing", "non_journal"]
ReviewStatus = Literal["open", "resolved", "dismissed"]

_LEDGER_OUTCOMES = frozenset({"ingested", "duplicate", "skipped", "error", "pending_review"})
_REVIEW_KINDS = frozenset(
    {"duplicate", "doi_unverified", "si_pairing", "metadata_missing", "non_journal"}
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LedgerEntry(_Model):
    sha256: str
    original_name: str
    outcome: LedgerOutcome
    citekey: str | None = None
    detail: str | None = None
    at: str


class Watermark(_Model):
    field: str
    last_scanned: str | None
    history: list[dict[str, Any]]


class ReviewItem(_Model):
    id: str
    kind: ReviewKind
    job_id: str | None = None
    payload: dict[str, Any]
    status: ReviewStatus
    decision: dict[str, Any] | None = None
    decided_by: str | None = None
    created_at: str
    decided_at: str | None = None


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _bad(message: str, **details: Any) -> PaperNestError:
    return PaperNestError(ErrorCode.INTERNAL, message, details)


def _not_yet(name: str, stage: int) -> NoReturn:
    raise PaperNestError(
        ErrorCode.NOT_SUPPORTED, f"{name} 尚未实现（阶段 {stage}）", {"function": name}
    )


class State:
    """对 `.papernest/state.db` 的薄封装；连接带 RLock，可被多线程共用。"""

    def __init__(self, library: Library) -> None:
        self.library = library
        self.db_path = library.state_dir / "state.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ---- 连接与建表 ----

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None:
                return self._conn
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # 手动控制事务；timeout 让多进程同时写时排队而不是立刻报 locked
            conn = sqlite3.connect(
                self.db_path, timeout=30, check_same_thread=False, isolation_level=None
            )
            conn.row_factory = sqlite3.Row
            # 切换 WAL 与建表需要独占锁，多个连接同时首次打开时会立刻报 locked，故重试
            for attempt in range(50):
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.executescript(_SCHEMA)
                    break
                except sqlite3.OperationalError:
                    if attempt == 49:
                        raise
                    time.sleep(0.05)
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                conn.execute(
                    "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row[0]) > SCHEMA_VERSION:
                conn.close()
                raise PaperNestError(
                    ErrorCode.LIBRARY_FORMAT_TOO_NEW,
                    f"state.db 版本 {row[0]} 高于本软件支持的 {SCHEMA_VERSION}。",
                )
            self._conn = conn
            return conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def schema_version(self) -> int:
        with self._lock:
            row = (
                self._connect()
                .execute("SELECT value FROM meta WHERE key='schema_version'")
                .fetchone()
            )
            return int(row[0])

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
            conn.execute("COMMIT")

    # ---- ingest_ledger（以源文件 sha256 为键） ----

    def ledger_get(self, sha256: str) -> LedgerEntry | None:
        with self._lock:
            row = (
                self._connect()
                .execute("SELECT * FROM ingest_ledger WHERE sha256=?", (sha256,))
                .fetchone()
            )
        return None if row is None else LedgerEntry.model_validate(dict(row))

    def ledger_put(
        self,
        sha256: str,
        original_name: str,
        outcome: LedgerOutcome,
        citekey: str | None = None,
        detail: str | None = None,
    ) -> LedgerEntry:
        """同一 sha256 再写即覆盖（重试、复核后结果会变）。"""
        if outcome not in _LEDGER_OUTCOMES:
            raise _bad(f"未知的台账结果：{outcome!r}", outcome=outcome)
        entry = LedgerEntry(
            sha256=sha256,
            original_name=original_name,
            outcome=outcome,
            citekey=citekey,
            detail=detail,
            at=_now(),
        )
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ingest_ledger"
                "(sha256, original_name, outcome, citekey, detail, at) VALUES(?,?,?,?,?,?)",
                (
                    entry.sha256,
                    entry.original_name,
                    entry.outcome,
                    entry.citekey,
                    entry.detail,
                    entry.at,
                ),
            )
        return entry

    def ledger_list(self, outcome: LedgerOutcome | None = None) -> list[LedgerEntry]:
        sql = "SELECT * FROM ingest_ledger"
        args: tuple[Any, ...] = ()
        if outcome is not None:
            sql += " WHERE outcome=?"
            args = (outcome,)
        with self._lock:
            rows = self._connect().execute(sql + " ORDER BY at, sha256", args).fetchall()
        return [LedgerEntry.model_validate(dict(r)) for r in rows]

    # ---- scan_watermarks ----

    def watermark_get(self, field: str) -> Watermark | None:
        with self._lock:
            row = (
                self._connect()
                .execute("SELECT * FROM scan_watermarks WHERE field=?", (field,))
                .fetchone()
            )
        if row is None:
            return None
        return Watermark(
            field=row["field"],
            last_scanned=row["last_scanned"],
            history=json.loads(row["history_json"] or "[]"),
        )

    def watermark_put(self, field: str, last_scanned: str, note: str | None = None) -> Watermark:
        """更新水位，并把上一个水位记进 history（读-改-写在同一事务内，不丢更新）。"""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT last_scanned, history_json FROM scan_watermarks WHERE field=?", (field,)
            ).fetchone()
            history: list[dict[str, Any]] = json.loads(row["history_json"] or "[]") if row else []
            if row is not None and row["last_scanned"] is not None:
                history.append(
                    {"last_scanned": row["last_scanned"], "replaced_at": _now(), "note": note}
                )
            conn.execute(
                "INSERT OR REPLACE INTO scan_watermarks(field, last_scanned, history_json) "
                "VALUES(?,?,?)",
                (field, last_scanned, json.dumps(history, ensure_ascii=False)),
            )
        return Watermark(field=field, last_scanned=last_scanned, history=history)

    # ---- review_items ----

    def review_add(
        self,
        kind: ReviewKind,
        payload: dict[str, Any],
        job_id: str | None = None,
    ) -> ReviewItem:
        if kind not in _REVIEW_KINDS:
            raise _bad(f"未知的审核类型：{kind!r}", kind=kind)
        item = ReviewItem(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            job_id=job_id,
            payload=payload,
            status="open",
            created_at=_now(),
        )
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO review_items(id, kind, job_id, payload_json, status, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    item.id,
                    item.kind,
                    item.job_id,
                    json.dumps(payload, ensure_ascii=False),
                    item.status,
                    item.created_at,
                ),
            )
        return item

    @staticmethod
    def _review_from_row(row: sqlite3.Row) -> ReviewItem:
        return ReviewItem(
            id=row["id"],
            kind=row["kind"],
            job_id=row["job_id"],
            payload=json.loads(row["payload_json"] or "{}"),
            status=row["status"],
            decision=json.loads(row["decision_json"]) if row["decision_json"] else None,
            decided_by=row["decided_by"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
        )

    def review_get(self, item_id: str) -> ReviewItem | None:
        with self._lock:
            row = (
                self._connect()
                .execute("SELECT * FROM review_items WHERE id=?", (item_id,))
                .fetchone()
            )
        return None if row is None else self._review_from_row(row)

    def review_list(
        self, status: ReviewStatus | None = "open", kind: ReviewKind | None = None
    ) -> list[ReviewItem]:
        clauses: list[str] = []
        args: list[Any] = []
        if status is not None:
            clauses.append("status=?")
            args.append(status)
        if kind is not None:
            clauses.append("kind=?")
            args.append(kind)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = (
                self._connect()
                .execute(f"SELECT * FROM review_items{where} ORDER BY created_at, id", args)
                .fetchall()
            )
        return [self._review_from_row(r) for r in rows]

    def review_resolve(
        self,
        item_id: str,
        decision: dict[str, Any],
        decided_by: str,
        dismissed: bool = False,
    ) -> ReviewItem:
        """只能裁决 open 的条目；重复裁决抛错而不是悄悄覆盖。"""
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM review_items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise PaperNestError(
                    ErrorCode.INTERNAL, f"找不到审核条目：{item_id}", {"id": item_id}
                )
            if row["status"] != "open":
                raise PaperNestError(
                    ErrorCode.INTERNAL,
                    f"审核条目已处理（{row['status']}）：{item_id}",
                    {"id": item_id, "status": row["status"]},
                )
            conn.execute(
                "UPDATE review_items SET status=?, decision_json=?, decided_by=?, decided_at=? "
                "WHERE id=?",
                (
                    "dismissed" if dismissed else "resolved",
                    json.dumps(decision, ensure_ascii=False),
                    decided_by,
                    _now(),
                    item_id,
                ),
            )
            row = conn.execute("SELECT * FROM review_items WHERE id=?", (item_id,)).fetchone()
        return self._review_from_row(row)

    # ---- 留待后续阶段的接口 ----

    def job_create(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("job_create", 5)

    def job_get(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("job_get", 5)

    def job_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("job_update", 5)

    def job_list(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("job_list", 5)

    def job_log(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("job_log", 5)

    def wanted_add(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("wanted_add", 8)

    def wanted_list(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("wanted_list", 8)

    def wanted_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("wanted_update", 8)

    def usage_add(self, *args: Any, **kwargs: Any) -> NoReturn:
        _not_yet("usage_add", 5)
