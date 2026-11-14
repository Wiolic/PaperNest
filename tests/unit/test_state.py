from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.library import Library
from papernest.core.state import SCHEMA_VERSION, State


@pytest.fixture
def state(tmp_path: Path) -> State:
    lib = Library.create(tmp_path / "lib", "t")
    s = State(lib)
    yield s
    s.close()


def test_tables_created_with_schema_version(state: State) -> None:
    assert state.schema_version() == SCHEMA_VERSION
    with sqlite3.connect(state.db_path) as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "meta",
        "jobs",
        "job_logs",
        "review_items",
        "ingest_ledger",
        "scan_watermarks",
        "wanted",
        "llm_usage",
    } <= names


def test_newer_schema_refused(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "lib", "t")
    s = State(lib)
    s.schema_version()
    s.close()
    with sqlite3.connect(s.db_path) as c:
        c.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    with pytest.raises(PaperNestError) as ei:
        State(lib).schema_version()
    assert ei.value.code == ErrorCode.LIBRARY_FORMAT_TOO_NEW


def test_ingest_resume_keyed_by_sha256(state: State) -> None:
    sha = "a" * 64
    assert state.ledger_get(sha) is None
    state.ledger_put(sha, "D:/old/path/paper.pdf", "ingested", citekey="2024-JACS-Foo-Bar")
    # 同内容换了路径与文件名：仍命中同一条台账
    hit = state.ledger_get(sha)
    assert hit is not None
    assert hit.citekey == "2024-JACS-Foo-Bar"
    state.ledger_put(sha, "E:/moved/renamed.pdf", "duplicate")
    assert len(state.ledger_list()) == 1
    entry = state.ledger_get(sha)
    assert entry is not None and entry.outcome == "duplicate"
    assert entry.original_name == "E:/moved/renamed.pdf"
    assert [e.sha256 for e in state.ledger_list("duplicate")] == [sha]
    assert state.ledger_list("error") == []


def test_ledger_rejects_unknown_outcome(state: State) -> None:
    with pytest.raises(PaperNestError):
        state.ledger_put("b" * 64, "x.pdf", "bogus")  # type: ignore[arg-type]


def test_state_write_is_atomic(state: State) -> None:
    sha = "c" * 64
    state.ledger_put(sha, "old.pdf", "skipped")
    # 事务中途失败：回滚后仍是旧版
    with pytest.raises(RuntimeError), state._tx() as conn:
        conn.execute("UPDATE ingest_ledger SET outcome='error' WHERE sha256=?", (sha,))
        raise RuntimeError("boom")
    entry = state.ledger_get(sha)
    assert entry is not None and entry.outcome == "skipped"
    # 回滚后连接仍可继续使用
    state.ledger_put(sha, "new.pdf", "ingested")
    entry = state.ledger_get(sha)
    assert entry is not None and entry.outcome == "ingested"


def test_watermark_roundtrip_and_history(state: State) -> None:
    assert state.watermark_get("Nickel") is None
    state.watermark_put("Nickel", "2024-01-01")
    wm = state.watermark_get("Nickel")
    assert wm is not None and wm.last_scanned == "2024-01-01" and wm.history == []
    wm2 = state.watermark_put("Nickel", "2024-06-01", note="rescan")
    assert wm2.last_scanned == "2024-06-01"
    assert [h["last_scanned"] for h in wm2.history] == ["2024-01-01"]
    again = state.watermark_get("Nickel")
    assert again == wm2


def test_review_add_list_resolve(state: State) -> None:
    a = state.review_add("duplicate", {"a": "X", "b": "X-2", "标题": "中文"}, job_id="j1")
    b = state.review_add("non_journal", {"file": "book.pdf"})
    assert a.status == "open" and a.payload["标题"] == "中文"
    assert {i.id for i in state.review_list()} == {a.id, b.id}
    assert [i.id for i in state.review_list(kind="non_journal")] == [b.id]

    done = state.review_resolve(a.id, {"keep": "X"}, "user")
    assert done.status == "resolved" and done.decision == {"keep": "X"}
    assert done.decided_by == "user" and done.decided_at is not None
    assert [i.id for i in state.review_list()] == [b.id]
    assert [i.id for i in state.review_list(status="resolved")] == [a.id]
    assert len(state.review_list(status=None)) == 2

    dismissed = state.review_resolve(b.id, {}, "user", dismissed=True)
    assert dismissed.status == "dismissed"
    assert state.review_get(b.id) == dismissed
    assert state.review_get("nope") is None


def test_review_resolve_errors(state: State) -> None:
    with pytest.raises(PaperNestError):
        state.review_resolve("missing", {}, "user")
    item = state.review_add("si_pairing", {})
    state.review_resolve(item.id, {}, "user")
    with pytest.raises(PaperNestError):
        state.review_resolve(item.id, {}, "user")
    with pytest.raises(PaperNestError):
        state.review_add("bogus", {})  # type: ignore[arg-type]


def test_concurrent_writes_no_lost_update(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "lib", "t")
    # 两个独立连接（模拟面板与命令行两个进程）同时写
    states = [State(lib), State(lib)]
    errors: list[BaseException] = []

    def work(idx: int) -> None:
        try:
            for n in range(40):
                states[idx].ledger_put(f"{idx}{n:03d}".ljust(64, "0"), "f.pdf", "ingested")
                states[idx].watermark_put("shared", f"{idx}-{n}")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(states[0].ledger_list()) == 80
    wm = states[0].watermark_get("shared")
    assert wm is not None
    # 80 次更新：1 个当前值 + 79 条历史，没有丢更新
    assert len(wm.history) == 79
    for s in states:
        s.close()


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.job_create(),
        lambda s: s.job_get(),
        lambda s: s.job_update(),
        lambda s: s.job_list(),
        lambda s: s.job_log(),
        lambda s: s.wanted_add(),
        lambda s: s.wanted_list(),
        lambda s: s.wanted_update(),
        lambda s: s.usage_add(),
    ],
)
def test_reserved_interfaces_not_supported(state: State, call) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(PaperNestError) as ei:
        call(state)
    assert ei.value.code == ErrorCode.NOT_SUPPORTED
