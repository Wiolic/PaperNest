from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from papernest.core.models import Note
from papernest.core.note_io import dump_note
from papernest.services import doctor
from papernest.services.context import ServiceContext

from .test_models import make_paper


def _by_code(report: doctor.DoctorReport) -> dict[str, list[doctor.DoctorIssue]]:
    out: dict[str, list[doctor.DoctorIssue]] = {}
    for i in report.issues:
        out.setdefault(i.code, []).append(i)
    return out


def _check(root: Path) -> doctor.DoctorReport:
    ctx = ServiceContext.open(root)
    try:
        return doctor.check(ctx)
    finally:
        ctx.close()


def _add_note(root: Path, **over: object) -> str:
    paper = make_paper(**over)
    (root / "notes" / f"{paper.citekey}.md").write_text(
        dump_note(Note(paper=paper)), encoding="utf-8", newline="\n"
    )
    return paper.citekey


def test_sample_library_reports_exactly_the_planted_issues() -> None:
    from tests.conftest import SMALL

    report = _check(SMALL)
    by = _by_code(report)
    assert set(by) == {
        "characterization_unmapped",
        "missing_main_file",
        "similar_titles",
        "tag_not_in_vocab",
        "missing_text",
    }
    assert report.ok
    assert by["missing_main_file"][0].citekeys == [
        "2021-Science-Layered-Oxide-Transport",
        "unknown-unknown-Sparse-Record",
    ]
    assert by["similar_titles"][0].citekeys == [
        "2022-Nature-Hybrid-Membrane-Design",
        "2022-Nature-Hybrid-Membrane-Design-2",
    ]
    assert by["tag_not_in_vocab"][0].data["tag"] == "未收录标签"
    assert by["tag_not_in_vocab"][0].citekeys == ["2023-Joule-Solar-Fuel-Cell"]
    assert by["characterization_unmapped"][0].data["counts"] == {"wacky probe": 1}
    # 有主文件的 10 篇都没有 text/
    assert len(by["missing_text"][0].citekeys) == 10
    assert by["missing_text"][0].severity == "info"
    assert report.summary == {"error": 0, "warning": 4, "info": 1}


def test_check_does_not_modify_library(small_lib_path: Path) -> None:
    def snapshot() -> dict[str, bytes]:
        return {
            str(p.relative_to(small_lib_path)): p.read_bytes()
            for p in small_lib_path.rglob("*")
            if p.is_file() and ".papernest" not in p.parts
        }

    before = snapshot()
    _check(small_lib_path)
    assert snapshot() == before


def test_note_invalid(small_lib_path: Path) -> None:
    (small_lib_path / "notes" / "2024-JACS-Broken-Note.md").write_text("no frontmatter", "utf-8")
    (small_lib_path / "notes" / "badname.md").write_text("x", "utf-8")
    by = _by_code(_check(small_lib_path))
    cks = {c for i in by["note_invalid"] for c in i.citekeys}
    assert cks == {"2024-JACS-Broken-Note", "badname"}
    assert all(i.severity == "error" for i in by["note_invalid"])
    assert not _check(small_lib_path).ok


def test_orphan_files_and_si_mismatch(small_lib_path: Path) -> None:
    papers = small_lib_path / "papers"
    (papers / "2099-Nope-Ghost.pdf").write_bytes(b"x")
    (papers / "2099-Nope-Ghost_SI.pdf").write_bytes(b"x")
    (papers / "2020-NatEnergy-Solid-State-Battery_SI.pdf").write_bytes(b"x")  # 存在未列出
    (small_lib_path / "text").mkdir(exist_ok=True)
    (small_lib_path / "text" / "2099-Nope-Ghost.txt").write_text("t", "utf-8")
    (papers / "2024-ACSNano-Quantum-Dot-Array_SI2.docx").unlink()  # 列出但不存在
    by = _by_code(_check(small_lib_path))
    orphan = by["orphan_file"][0]
    assert orphan.data["papers"] == ["2099-Nope-Ghost.pdf", "2099-Nope-Ghost_SI.pdf"]
    assert orphan.data["text"] == ["2099-Nope-Ghost.txt"]
    mism = {i.citekeys[0]: i.data for i in by["si_mismatch"]}
    assert mism["2020-NatEnergy-Solid-State-Battery"]["unlisted_on_disk"] == [
        "2020-NatEnergy-Solid-State-Battery_SI.pdf"
    ]
    assert mism["2024-ACSNano-Quantum-Dot-Array"]["listed_missing"] == [
        "2024-ACSNano-Quantum-Dot-Array_SI2.docx"
    ]


def test_sibling_citekey_files_do_not_cross_match(small_lib_path: Path) -> None:
    # X-2.pdf 不能被当成 X 的文件：删掉 X.pdf 后 X 应缺主文件
    (small_lib_path / "papers" / "2022-Nature-Hybrid-Membrane-Design.pdf").unlink()
    by = _by_code(_check(small_lib_path))
    assert "2022-Nature-Hybrid-Membrane-Design" in by["missing_main_file"][0].citekeys
    assert "2022-Nature-Hybrid-Membrane-Design-2" not in by["missing_main_file"][0].citekeys
    assert "orphan_file" not in by


def test_text_present_suppresses_missing_text(small_lib_path: Path) -> None:
    (small_lib_path / "text").mkdir(exist_ok=True)
    for ck in ("2020-NatEnergy-Solid-State-Battery",):
        (small_lib_path / "text" / f"{ck}.txt").write_text("t", "utf-8")
    by = _by_code(_check(small_lib_path))
    assert "2020-NatEnergy-Solid-State-Battery" not in by["missing_text"][0].citekeys


def test_duplicate_doi_and_journal_vocab_and_related(small_lib_path: Path) -> None:
    _add_note(
        small_lib_path,
        citekey="2025-Mystery-Other-Topic",
        title="Completely different subject",
        doi="10.1000/fix.0001",
        journal="Journal of Imaginary Results",
        related=["2025-Gone-Missing-Paper"],
    )
    (small_lib_path / "papers" / "2025-Mystery-Other-Topic.pdf").write_bytes(b"x")
    by = _by_code(_check(small_lib_path))
    assert by["duplicate_doi"][0].citekeys == [
        "2023-JACS-Nickel-Catalyst-Selective",
        "2025-Mystery-Other-Topic",
    ]
    assert by["journal_not_in_vocab"][0].data["journal"] == "Journal of Imaginary Results"
    assert by["dangling_related"][0].data["missing"] == ["2025-Gone-Missing-Paper"]


def test_unreviewed_vocab(small_lib_path: Path) -> None:
    from papernest.core.vocab import Vocab

    v = Vocab.load(small_lib_path / "vocab")
    v.add_tag("新标签")
    v.save()
    by = _by_code(_check(small_lib_path))
    issue = by["unreviewed_vocab"][0]
    assert issue.severity == "info" and issue.data["names"] == ["新标签"]


def test_dangling_topic_ref(small_lib_path: Path) -> None:
    topics = small_lib_path / "topics"
    topics.mkdir(exist_ok=True)
    (topics / "oer.md").write_text(
        "见 [[2020-NatEnergy-Solid-State-Battery]]、[[2020-Nat-Gone-Forever|别名]]，"
        "以及主题链接 [[some topic]]。\n",
        "utf-8",
    )
    by = _by_code(_check(small_lib_path))
    issue = by["dangling_topic_ref"][0]
    assert issue.citekeys == ["2020-Nat-Gone-Forever"]
    assert issue.data["topic"] == "oer.md"


def test_performance_orphan_and_invalid(small_lib_path: Path) -> None:
    csv_path = small_lib_path / "data" / "performance.csv"
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        f.write(
            "2023-JACS-Nickel-Catalyst-Selective,2023-JACS-Nickel-Catalyst-Selective#1,half-cell,,,,,,,,,,,,\n"
        )
        f.write("2099-Gone-Paper-Here,2099-Gone-Paper-Here#1,MEA,,,,,,,,,,,,\n")
        f.write("2023-JACS-Nickel-Catalyst-Selective,x#2,not-a-type,,,,,,,,,,,,\n")
    by = _by_code(_check(small_lib_path))
    assert by["performance_orphan"][0].citekeys == ["2099-Gone-Paper-Here"]
    assert by["performance_invalid"][0].data["lines"] == [4]


def test_inbox_pending(small_lib_path: Path) -> None:
    inbox = small_lib_path / "inbox"
    inbox.mkdir(exist_ok=True)
    (inbox / "new1.pdf").write_bytes(b"x")
    (inbox / "new2.pdf").write_bytes(b"x")
    issue = _by_code(_check(small_lib_path))["inbox_pending"][0]
    assert issue.severity == "info" and issue.data["count"] == 2


def test_clean_library_has_no_issues(tmp_path: Path) -> None:
    from papernest.core.library import Library

    Library.create(tmp_path / "empty", "空库")
    report = _check(tmp_path / "empty")
    assert report.ok and report.issues == []


@pytest.fixture(autouse=True)
def _no_stale_index(small_lib_path: Path) -> None:
    shutil.rmtree(small_lib_path / ".papernest", ignore_errors=True)
