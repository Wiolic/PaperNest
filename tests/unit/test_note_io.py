from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from papernest.core.errors import PaperNestError
from papernest.core.library import Library
from papernest.core.models import LibraryConfig, Note, Section, SectionCfg
from papernest.core.note_io import dump_note, parse_note, read_note, write_note
from tests.unit.test_models import make_paper

CFG = LibraryConfig().note.sections
SMALL = Path(__file__).resolve().parents[1] / "fixtures" / "library_small"
SMALL_NOTES = sorted((SMALL / "notes").glob("*.md"))


def roundtrip_check(n: Note) -> None:
    text = dump_note(n)
    assert text.endswith("\n") and not text.endswith("\n\n")
    n2 = parse_note(text, CFG)
    assert n2 == n
    assert dump_note(n2) == text


@pytest.mark.parametrize("path", SMALL_NOTES, ids=lambda p: p.stem)
def test_fixture_notes_roundtrip(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    n = parse_note(text, CFG)
    assert dump_note(n) == text
    roundtrip_check(n)


def test_fixture_count() -> None:
    assert len(SMALL_NOTES) == 12


VALUES = [
    "plain",
    "a: b",
    "a:b",
    "# not comment",
    "x # y",
    'say "hi"',
    "it's",
    "true",
    "null",
    "123",
    "1e3",
    "2024-01-01",
    "~",
    "- dash",
    "[x]",
    "{y}",
    "a, b",
    "  padded  ",
    "",
    "multi\nline",
    "tab\there",
    "\u0085nel",
    "中文：冒号",
    "back\\slash",
    "%percent",
    "@at",
    "`tick",
    "yes",
    "No",
    "0x1F",
    "12:30:00",
    "Ir(III), Ru(IV) oxide",
    "Smith, Jr.",
]


@pytest.mark.parametrize("value", VALUES)
def test_list_fields_with_commas_roundtrip(value: str) -> None:
    n = Note(
        paper=make_paper(
            title=value.replace("\n", " ").strip() or "t",
            keywords=[value, "other"],
            authors=[value],
            methods=value,
            system=value,
        )
    )
    text = dump_note(n)
    fm: dict[str, Any] = yaml.safe_load(text.split("---\n")[1])
    assert fm["keywords"] == [value, "other"]
    assert fm["methods"] == value
    assert fm["authors"] == [value]
    roundtrip_check(parse_note(text, CFG))


def test_frontmatter_values_with_colon_roundtrip() -> None:
    n = Note(paper=make_paper(title="Part I: A study - with # hash", system="A: B"))
    text = dump_note(n)
    assert yaml.safe_load(text.split("---\n")[1])["title"] == "Part I: A study - with # hash"
    roundtrip_check(n)


def test_empty_field_does_not_swallow_newline() -> None:
    text = dump_note(Note(paper=make_paper(rating=None, volume=None, issue=None)))
    assert "\nrating:\n" in text
    n = parse_note(text, CFG)
    assert n.paper.rating is None and n.paper.volume is None and n.paper.issue is None
    assert n.paper.entry_type == "article"


def test_dump_is_lf_and_deterministic() -> None:
    n = Note(
        paper=make_paper(),
        sections=[Section(id="summary", heading=CFG[0].heading, content="a\r\nb")],
    )
    t = dump_note(n)
    assert "\r" not in t and not t.startswith("﻿")
    assert dump_note(n) == t


def test_notes_written_with_lf_only(tmp_path: Path) -> None:
    n = Note(
        paper=make_paper(),
        sections=[Section(id="summary", heading=CFG[0].heading, content="a\nb")],
    )
    p = tmp_path / "2024-JACS-Some-Title.md"
    write_note(p, n)
    assert b"\r" not in p.read_bytes()
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")


def test_parse_accepts_crlf_and_bom(tmp_path: Path) -> None:
    n = Note(
        paper=make_paper(),
        sections=[Section(id="summary", heading=CFG[0].heading, content="x\ny")],
    )
    p = tmp_path / "2024-JACS-Some-Title.md"
    p.write_bytes(b"\xef\xbb\xbf" + dump_note(n).replace("\n", "\r\n").encode())
    assert read_note(p, CFG) == n


def test_section_ids_order_and_unknown_kept() -> None:
    h = {c.id: c.heading for c in CFG}
    text = (
        dump_note(Note(paper=make_paper())).rstrip("\n")
        + "\n\nintro text\n\n## 自定义 A\naaa\n\n"
        + f"## {h['caveats']}\ncav\n\n## {h['summary']}\nsum\n"
        + "\n## 自定义 B\nbbb\n\n## "
        + h["summary"]
        + "\ndup\n"
    )
    n = parse_note(text, CFG)
    assert [(s.id, s.heading) for s in n.sections] == [
        (None, ""),
        ("summary", h["summary"]),
        ("caveats", h["caveats"]),
        (None, "自定义 A"),
        (None, "自定义 B"),
        (None, h["summary"]),
    ]
    assert n.section("summary") == "sum"
    assert n.sections[0].content == "intro text"
    roundtrip_check(n)


def test_empty_sections_roundtrip() -> None:
    n = Note(
        paper=make_paper(),
        sections=[
            Section(id="summary", heading=CFG[0].heading, content=""),
            Section(id="caveats", heading=CFG[5].heading, content="x"),
        ],
    )
    roundtrip_check(n)


def test_custom_section_cfg_headings() -> None:
    cfg = [SectionCfg(id="s", heading="Summary")]
    text = dump_note(Note(paper=make_paper(), sections=[Section(heading="Summary", content="c")]))
    assert parse_note(text, cfg).sections[0].id == "s"


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter\n",
        "---\ncitekey: x\n",
        "---\n- a\n- b\n---\n",
        "---\n: : :\n  bad: [\n---\n",
        "---\ncitekey: 2024-A-B\n---\n",  # 缺必填字段
    ],
)
def test_parse_invalid(text: str) -> None:
    with pytest.raises(PaperNestError) as ei:
        parse_note(text, CFG)
    assert ei.value.code == "note_invalid"


def test_unknown_key_is_error() -> None:
    text = dump_note(Note(paper=make_paper())).replace("---\n", "---\nmystery: 1\n", 1)
    with pytest.raises(PaperNestError) as ei:
        parse_note(text, CFG)
    assert ei.value.code == "note_invalid"


def test_read_note_citekey_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "2024-JACS-Other-Name.md"
    write_note(p, Note(paper=make_paper()))
    with pytest.raises(PaperNestError) as ei:
        read_note(p, CFG)
    assert ei.value.code == "note_invalid"


def test_read_note_bad_utf8(tmp_path: Path) -> None:
    p = tmp_path / "2024-JACS-Some-Title.md"
    p.write_bytes(b"---\n\xff\xfe\n---\n")
    with pytest.raises(PaperNestError):
        read_note(p, CFG)


def test_read_fixture_via_library(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    n = read_note(lib.note_path("2023-Joule-Solar-Fuel-Cell"), lib.config.note.sections)
    assert n.paper.authors == ["王小明", "李华"]
    assert n.section("summary") == "中文内容。"
