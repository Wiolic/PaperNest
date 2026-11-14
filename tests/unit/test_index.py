from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from papernest.core import index as index_mod
from papernest.core.index import Index, SearchQuery
from papernest.core.library import Library
from papernest.core.models import Note, Section
from papernest.core.note_io import dump_note, read_note, write_note
from papernest.core.textsim import find_similar_titles

from .test_models import make_paper


@pytest.fixture
def lib(small_lib_path: Path) -> Library:
    return Library.open(small_lib_path)


@pytest.fixture
def idx(lib: Library) -> Index:
    i = Index(lib)
    i.sync()
    return i


def _q(**kw: object) -> SearchQuery:
    return SearchQuery.model_validate(kw)


def _cks(idx: Index, **kw: object) -> list[str]:
    return [r.citekey for r in idx.search(_q(limit=100, **kw)).items]


def test_sync_sample_library(lib: Library) -> None:
    idx = Index(lib)
    report = idx.sync()
    assert len(report.added) == 12 and not report.errors
    assert report.updated == [] and report.removed == []
    assert idx.search(_q()).library_total == 12
    again = idx.sync()
    assert again.added == [] and again.unchanged == 12


def test_get_loads_lists(idx: Index) -> None:
    row = idx.get("2023-JACS-Nickel-Catalyst-Selective")
    assert row is not None
    assert row.tags == ["电催化", "单原子"]
    assert row.characterization == ["XAS", "in situ Raman"]
    assert row.characterization_unmapped == ["wacky probe"]
    assert row.is_top_journal and row.has_pdf and row.si_count == 0
    assert idx.get("nope") is None
    sparse = idx.get("unknown-unknown-Sparse-Record")
    assert sparse is not None and sparse.year is None and sparse.journal is None
    assert not sparse.has_pdf


def test_has_pdf_and_si_count_agree_with_library(lib: Library, idx: Index) -> None:
    for ck in lib.list_citekeys():
        row = idx.get(ck)
        assert row is not None
        assert row.has_pdf == (lib.main_file(ck) is not None), ck
        assert row.si_count == len(lib.si_files(ck)), ck
    # X 与 X-2 互不影响
    a = idx.get("2022-Nature-Hybrid-Membrane-Design")
    assert a is not None and a.has_pdf
    two = idx.get("2024-ACSNano-Quantum-Dot-Array")
    assert two is not None and two.si_count == 2


def test_files_refreshed_without_touching_note(lib: Library, idx: Index) -> None:
    ck = "unknown-unknown-Sparse-Record"
    (lib.papers_dir / f"{ck}.pdf").write_bytes(b"x")
    (lib.papers_dir / f"{ck}_SI.pdf").write_bytes(b"x")
    report = idx.sync()
    assert report.updated == [] and report.added == []
    row = idx.get(ck)
    assert row is not None and row.has_pdf and row.si_count == 1


def test_sync_incremental_reparses_only_changed_file(
    lib: Library, idx: Index, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = index_mod.read_note

    def spy(path: Path, cfg: object) -> Note:
        calls.append(path.stem)
        return real(path, cfg)  # type: ignore[arg-type]

    monkeypatch.setattr(index_mod, "read_note", spy)
    ck = "2021-Science-Layered-Oxide-Transport"
    path = lib.note_path(ck)
    note = read_note(path, lib.config.note.sections)
    note.paper.title = "A brand new title"
    write_note(path, note)
    report = idx.sync()
    assert calls == [ck]
    assert report.updated == [ck] and report.added == [] and report.unchanged == 11
    row = idx.get(ck)
    assert row is not None and row.title == "A brand new title"


def test_touch_without_content_change_does_not_reparse(
    lib: Library, idx: Index, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = index_mod.read_note
    monkeypatch.setattr(index_mod, "read_note", lambda p, c: (calls.append(p.stem), real(p, c))[1])
    path = lib.note_path("2021-Science-Layered-Oxide-Transport")
    future = time.time() + 100
    os.utime(path, (future, future))
    report = idx.sync()
    assert calls == [] and report.updated == [] and report.unchanged == 12
    assert idx.sync().unchanged == 12  # mtime 已回写，下次走快速路径


def test_sync_add_and_remove(lib: Library, idx: Index) -> None:
    ck = "2025-JACS-Brand-New"
    write_note(lib.note_path(ck), Note(paper=make_paper(citekey=ck, title="Brand new")))
    report = idx.sync()
    assert report.added == [ck]
    lib.note_path("unknown-unknown-Sparse-Record").unlink()
    report = idx.sync()
    assert report.removed == ["unknown-unknown-Sparse-Record"] and report.added == []
    assert idx.get("unknown-unknown-Sparse-Record") is None
    assert idx.search(_q()).library_total == 12


def test_sync_records_parse_errors(lib: Library, idx: Index) -> None:
    ck = "2021-Science-Layered-Oxide-Transport"
    lib.note_path(ck).write_text("not a note", encoding="utf-8")
    report = idx.sync()
    assert [e.citekey for e in report.errors] == [ck]
    assert report.removed == [ck]
    assert idx.get(ck) is None
    assert [e.citekey for e in idx.errors()] == [ck]
    # 没修好之前每次同步都继续报告，且不重新解析
    again = idx.sync()
    assert [e.citekey for e in again.errors] == [ck]
    # 修好之后恢复
    good = Note(paper=make_paper(citekey=ck, title="Fixed"))
    write_note(lib.note_path(ck), good)
    report = idx.sync()
    assert report.added == [ck] and not report.errors and idx.errors() == []


def test_citekey_filename_mismatch_is_an_error(lib: Library, idx: Index) -> None:
    bad = lib.notes_dir / "2025-JACS-Wrong-Name.md"
    bad.write_text(dump_note(Note(paper=make_paper(citekey="2025-JACS-Other"))), encoding="utf-8")
    report = idx.sync()
    assert [e.citekey for e in report.errors] == ["2025-JACS-Wrong-Name"]


def test_rebuild_matches_incremental(lib: Library, idx: Index) -> None:
    before = idx.search(_q(limit=100)).items
    report = idx.rebuild()
    assert len(report.added) == 12
    assert idx.search(_q(limit=100)).items == before


def test_schema_mismatch_rebuilds_database(lib: Library, idx: Index) -> None:
    idx.close()
    conn = sqlite3.connect(idx.db_path)
    conn.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    fresh = Index(lib)
    assert len(fresh.sync().added) == 12


def test_corrupt_database_is_recreated(lib: Library) -> None:
    db = lib.state_dir / "index.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"this is not sqlite" * 100)
    assert len(Index(lib).sync().added) == 12


def test_vocab_change_refreshes_derived_columns(lib: Library, idx: Index) -> None:
    ck = "2022-AdvMater-Copper-Silver-Interface"
    row = idx.get(ck)
    assert row is not None and row.is_top_journal
    p = lib.root / "vocab" / "journals.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("top: true", "top: false"), encoding="utf-8")
    report = idx.sync()
    assert len(report.updated) == 12  # 词表变了，派生列（顶刊标记等）全部重算
    row = idx.get(ck)
    assert row is not None and not row.is_top_journal


def test_search_text_fields(idx: Index) -> None:
    assert _cks(idx, text="Ruthenium") == ["2021-JACS-Ruthenium-Acid-Stability"]
    assert _cks(idx, text="catalyst stability")  # 多词 AND，关键词字段
    assert _cks(idx, text="界面") == ["2023-Joule-Solar-Fuel-Cell"]  # 中文子串
    assert _cks(idx, text="燃料电池") == ["2023-Joule-Solar-Fuel-Cell"]
    assert _cks(idx, text="Someya") == []
    assert _cks(idx, text="   ") == _cks(idx)


@pytest.mark.parametrize(
    "text", ['"', "AND OR", "a*", "NEAR(", "title:", "(", "-", "x' OR 1=1 --", '"quoted']
)
def test_search_text_never_raises_syntax_error(idx: Index, text: str) -> None:
    idx.search(_q(text=text))


def test_search_text_in_body_and_authors(lib: Library, idx: Index) -> None:
    ck = "2025-JACS-Body-Search"
    paper = make_paper(citekey=ck, title="Plain", authors=["Zhang Wei", "Van der Waals"])
    note = Note(
        paper=paper,
        sections=[
            Section(id="summary", heading="三句话总结", content="Xylophone resonance observed")
        ],
    )
    write_note(lib.note_path(ck), note)
    idx.sync()
    assert _cks(idx, text="xylophone") == [ck]
    assert _cks(idx, text="waals") == [ck]
    assert _cks(idx, text="张") == []


def test_search_fulltext_opt_in(lib: Library, idx: Index) -> None:
    ck = "2021-Science-Layered-Oxide-Transport"
    (lib.root / "text" / f"{ck}.txt").write_text("deep within: zeppelin anomaly", encoding="utf-8")
    idx.sync()
    assert _cks(idx, text="zeppelin") == []
    assert _cks(idx, text="zeppelin", include_fulltext=True) == [ck]
    # 改文字后重新索引，删文件后移除
    (lib.root / "text" / f"{ck}.txt").write_text("something else entirely", encoding="utf-8")
    idx.sync()
    assert _cks(idx, text="zeppelin", include_fulltext=True) == []
    assert _cks(idx, text="entirely", include_fulltext=True) == [ck]
    (lib.root / "text" / f"{ck}.txt").unlink()
    idx.sync()
    assert _cks(idx, text="entirely", include_fulltext=True) == []


def test_search_filters(idx: Index) -> None:
    assert len(_cks(idx, tags_any=["电催化"])) == 5
    assert set(_cks(idx, tags_any=["膜", "电池"])) == {
        "2022-Nature-Hybrid-Membrane-Design",
        "2022-Nature-Hybrid-Membrane-Design-2",
        "2020-NatEnergy-Solid-State-Battery",
    }
    assert _cks(idx, tags_all=["电催化", "单原子"]) == ["2023-JACS-Nickel-Catalyst-Selective"]
    assert _cks(idx, tags_all=["电催化", "膜"]) == []
    # 期刊别名与大小写都能命中
    assert set(_cks(idx, journals=["J. Am. Chem. Soc."])) == {
        "2021-JACS-Ruthenium-Acid-Stability",
        "2023-JACS-Nickel-Catalyst-Selective",
    }
    assert "2024-ACSNano-Quantum-Dot-Array" not in _cks(idx, top_journals_only=True)
    assert "2023-NatCommun-Quoted-Title-Hash" not in _cks(idx, top_journals_only=True)
    assert "2023-JACS-Nickel-Catalyst-Selective" in _cks(idx, top_journals_only=True)
    assert set(_cks(idx, year_from=2023, year_to=2024)) == {
        "2023-JACS-Nickel-Catalyst-Selective",
        "2023-Joule-Solar-Fuel-Cell",
        "2023-NatCommun-Quoted-Title-Hash",
        "2024-ACSNano-Quantum-Dot-Array",
    }
    assert _cks(idx, types=["review"]) == ["2021-Science-Layered-Oxide-Transport"]
    assert len(_cks(idx, status=["unread"])) + len(_cks(idx, status=["skimmed", "read"])) == 12
    assert set(_cks(idx, has_pdf=False)) == {
        "unknown-unknown-Sparse-Record",
        "2021-Science-Layered-Oxide-Transport",
    }
    assert len(_cks(idx, has_pdf=True)) == 10


def test_search_paging_and_total(idx: Index) -> None:
    res = idx.search(_q(limit=5, offset=10, sort="title"))
    assert res.total == 12 and res.library_total == 12 and len(res.items) == 2
    res = idx.search(_q(limit=5, tags_any=["电催化"]))
    assert res.total == 5 and res.library_total == 12


def test_search_sorts(idx: Index) -> None:
    years = [r.year for r in idx.search(_q(limit=100, sort="year_desc")).items]
    assert years[:3] == [2024, 2023, 2023] and years[-2:] == [None, None]
    titles = [r.title.casefold() for r in idx.search(_q(limit=100, sort="title")).items]
    assert titles == sorted(titles)
    rel = idx.search(_q(text="membrane", sort="relevance")).items
    assert {r.citekey for r in rel} >= {"2022-Nature-Hybrid-Membrane-Design"}
    # 没有查询词时 relevance 退化为默认排序
    assert _cks(idx, sort="relevance") == _cks(idx)


def test_recent_added_not_affected_by_rewrite(lib: Library, idx: Index) -> None:
    ck = "2020-NatEnergy-Solid-State-Battery"
    before = _cks(idx)
    future = time.time() + 300
    os.utime(lib.note_path(ck), (future, future))
    idx.sync()
    assert _cks(idx) == before
    # `added` 带时分秒，同一天的两篇按时间排序
    for k, t in (
        ("2025-JACS-Early", datetime(2026, 1, 1, 9, 0, 0)),
        ("2025-JACS-Late", datetime(2026, 1, 1, 17, 30, 5)),
    ):
        write_note(lib.note_path(k), Note(paper=make_paper(citekey=k, added=t)))
    idx.sync()
    assert _cks(idx)[:2] == ["2025-JACS-Late", "2025-JACS-Early"]


def test_facets(idx: Index) -> None:
    f = idx.facets()
    tags = {x.value: x.count for x in f.tags}
    assert tags["电催化"] == 5 and tags["未收录标签"] == 1
    assert f.tags[0].value == "电催化"
    journals = {x.value: x.count for x in f.journals}
    assert journals["Nature"] == 3  # Nature 两篇 Hybrid + 无年份那篇
    assert journals["Journal of the American Chemical Society"] == 2
    assert [x.value for x in f.years][:2] == [2024, 2023]
    assert sum(x.count for x in f.types) == 11
    assert sum(x.count for x in f.status) == 12


def test_facets_merge_journal_aliases(lib: Library, idx: Index) -> None:
    ck = "2025-JACS-Alias-Journal"
    write_note(lib.note_path(ck), Note(paper=make_paper(citekey=ck, journal="J. Am. Chem. Soc.")))
    idx.sync()
    jacs = [x for x in idx.facets().journals if x.count == 3 and x.value != "Nature"]
    assert len(jacs) == 1  # 别名写法与全名合并为一项
    assert len([x for x in idx.facets().journals if "Chem" in str(x.value)]) == 1


def test_keyword_index_counts_from_structured_lists(idx: Index) -> None:
    counts = idx.keyword_counts()
    d = {c.value: c.count for c in counts}
    # 带逗号的关键词是单个整体，不被切开
    assert d["Cu(111), Ag"] == 1 and d["tandem, catalysis"] == 1 and d["[brackets]"] == 1
    assert "Cu(111)" not in d and "Ag" not in d
    assert d["catalyst"] == 10
    # 次数降序，次数相同按字典序，结果稳定
    pairs = [(-c.count, str(c.value)) for c in counts]
    assert pairs == sorted(pairs)
    assert idx.keyword_counts() == counts


def test_characterization_counts_never_contain_unmapped_prefix(lib: Library, idx: Index) -> None:
    ck = "2025-JACS-Legacy-Prefix"
    paper = make_paper(citekey=ck, characterization_unmapped=["unmapped:EQE"])
    write_note(lib.note_path(ck), Note(paper=paper))
    idx.sync()
    all_ = {c.value for c in idx.characterization_counts()}
    assert "EQE" in all_ and not any(str(v).startswith("unmapped:") for v in all_)
    assert {c.value for c in idx.characterization_counts(mapped=True)} == {
        "STM",
        "XAS",
        "in situ Raman",
    }
    assert {c.value for c in idx.characterization_counts(mapped=False)} == {"wacky probe", "EQE"}


def test_find_by_doi_and_all_titles(lib: Library, idx: Index) -> None:
    assert idx.find_by_doi("") == [] and idx.find_by_doi("10.1/none") == []
    for ck, doi in (("2025-JACS-A-One", "10.300/Abc"), ("2025-JACS-B-Two", "10.300/abc")):
        write_note(lib.note_path(ck), Note(paper=make_paper(citekey=ck, doi=doi)))
    idx.sync()
    assert idx.find_by_doi("https://doi.org/10.300/ABC ") == ["2025-JACS-A-One", "2025-JACS-B-Two"]
    titles = idx.all_titles()
    assert len(titles) == 14 and titles == sorted(titles)


def test_dedupe_via_index_finds_planted_pair(idx: Index) -> None:
    pairs = find_similar_titles(idx.all_titles(), 0.9)
    assert [(a, b) for a, b, _ in pairs] == [
        ("2022-Nature-Hybrid-Membrane-Design", "2022-Nature-Hybrid-Membrane-Design-2")
    ]


def test_title_dedupe_does_not_bleed_across_bib_entries(lib: Library, idx: Index) -> None:
    # 缺 DOI 的条目不会拿到相邻条目的 DOI
    write_note(
        lib.note_path("2025-JACS-No-Doi"),
        Note(paper=make_paper(citekey="2025-JACS-No-Doi", doi=None)),
    )
    write_note(
        lib.note_path("2025-JACS-Has-Doi"),
        Note(paper=make_paper(citekey="2025-JACS-Has-Doi", doi="10.1/x")),
    )
    idx.sync()
    assert idx.find_by_doi("10.1/x") == ["2025-JACS-Has-Doi"]
    row = idx.get("2025-JACS-No-Doi")
    assert row is not None and row.doi is None


def test_performance_table_loaded(lib: Library, idx: Index) -> None:
    assert idx.performance_rows() == []
    csv_path = lib.root / "data" / "performance.csv"
    header = csv_path.read_text(encoding="utf-8")
    cols = header.strip().split(",")
    good = dict.fromkeys(cols, "")
    good.update(
        citekey="2020-NatEnergy-Solid-State-Battery",
        row_id="2020-NatEnergy-Solid-State-Battery#1",
        test_type="MEA",
        overpotential_mV="280",
    )
    bad = dict(good, row_id="x#2", test_type="bogus")
    lines = [",".join(r[c] for c in cols) for r in (good, bad)]
    csv_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    idx.sync()
    rows = idx.performance_rows()
    assert [r.row_id for r in rows] == ["2020-NatEnergy-Solid-State-Battery#1"]
    assert rows[0].overpotential_mV == 280.0
    assert idx.performance_rows("nope") == []
    assert len(idx.performance_rows("2020-NatEnergy-Solid-State-Battery")) == 1


def test_index_db_lives_in_state_dir_and_notes_untouched(lib: Library) -> None:
    before = {p.name: p.read_bytes() for p in lib.notes_dir.iterdir()}
    Index(lib).sync()
    assert (lib.state_dir / "index.db").is_file()
    assert {p.name: p.read_bytes() for p in lib.notes_dir.iterdir()} == before


def _make_many(lib: Library, n: int) -> None:
    for i in range(n):
        ck = f"2024-JACS-Paper-{i}"
        p = make_paper(citekey=ck, title=f"Title number {i}", keywords=[f"kw{i % 7}"])
        write_note(lib.note_path(ck), Note(paper=p))


def test_sync_scales_to_three_hundred_notes(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "big", "big")
    _make_many(lib, 300)
    idx = Index(lib)
    t0 = time.perf_counter()
    assert len(idx.sync().added) == 300
    assert time.perf_counter() - t0 < 30
    t0 = time.perf_counter()
    assert idx.sync().unchanged == 300
    assert time.perf_counter() - t0 < 5


def test_concurrent_search_from_threads(idx: Index) -> None:
    from concurrent.futures import ThreadPoolExecutor

    fn: Callable[[int], int] = lambda _i: idx.search(_q(text="catalyst")).total  # noqa: E731
    with ThreadPoolExecutor(4) as ex:
        assert set(ex.map(fn, range(20))) == {idx.search(_q(text="catalyst")).total}
