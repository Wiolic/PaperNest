from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from papernest.core.models import (
    LibraryConfig,
    Note,
    Paper,
    PerformanceRow,
    Section,
    normalize_doi,
)


def make_paper(**over: Any) -> Paper:
    data: dict[str, Any] = dict(
        citekey="2024-JACS-Some-Title",
        title="T",
        authors=["A B"],
        year=2024,
        journal=None,
        doi=None,
        volume=None,
        issue=None,
        pages=None,
        entry_type="article",
        type=None,
        tags=[],
        keywords=[],
        methods="",
        characterization=[],
        characterization_unmapped=[],
        system="",
        status="unread",
        rating=None,
        related=[],
        si_files=[],
        added=datetime(2025, 1, 1, 0, 0, 0),
    )
    data.update(over)
    return Paper(**data)


@pytest.mark.parametrize(
    "ck", ["2024-JACS-Foo", "unknown-unknown-Foo-Bar", "2024-JACS-Foo-2", "2024-Nature-Ir-OER-3"]
)
def test_citekey_valid(ck: str) -> None:
    assert make_paper(citekey=ck).citekey == ck


@pytest.mark.parametrize(
    "ck",
    [
        "",
        "2024-JACS",
        "24-JACS-Foo",
        "2024_JACS_Foo",
        "2024-JACS-Foo\n",
        "../x-y-z",
        "2024-JACS-Foo bar",
    ],
)
def test_citekey_invalid(ck: str) -> None:
    with pytest.raises(ValidationError):
        make_paper(citekey=ck)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://doi.org/10.1000/ABC", "10.1000/abc"),
        ("doi:10.1000/ABC ", "10.1000/abc"),
        ("  DOI:https://doi.org/10.1/X", "10.1/x"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_doi_normalization(raw: str | None, expected: str | None) -> None:
    assert normalize_doi(raw) == expected
    assert make_paper(doi=raw).doi == expected


def test_title_cleanup_and_nonempty() -> None:
    assert make_paper(title="  A\nB \r\n C ").title == "A B C"
    with pytest.raises(ValidationError):
        make_paper(title="  \n ")


@pytest.mark.parametrize(
    "field,val", [("rating", 0), ("rating", 6), ("year", 1799), ("year", 2101)]
)
def test_range_checks(field: str, val: int) -> None:
    with pytest.raises(ValidationError):
        make_paper(**{field: val})


def test_extra_keys_forbidden() -> None:
    with pytest.raises(ValidationError):
        make_paper(unknown_key=1)


def test_added_microseconds_dropped() -> None:
    assert make_paper(added=datetime(2025, 1, 1, 1, 2, 3, 999)).added == datetime(
        2025, 1, 1, 1, 2, 3
    )


def test_author_names_not_split_by_last_word() -> None:
    names = ["Johannes van der Waals", "Ana de la Cruz", "John Smith Jr.", "Madonna", "王小明"]
    assert make_paper(authors=names).authors == names


def test_section_content_normalization() -> None:
    s = Section(heading=" H \n", content="\n\n  indented\nline\r\n\n  \n")
    assert s.heading == "H"
    assert s.content == "  indented\nline"


def test_note_section_lookup() -> None:
    n = Note(
        paper=make_paper(),
        sections=[Section(id="a", heading="A", content="x"), Section(heading="Z", content="y")],
    )
    assert n.section("a") == "x"
    assert n.section("missing") == ""
    assert n.body_markdown() == "## A\nx\n\n## Z\ny\n"


def test_performance_row_blank_numeric() -> None:
    r = PerformanceRow(
        citekey="2024-A-B", row_id="2024-A-B#1", overpotential_mV="", cell_voltage_V=1.6
    )
    assert r.overpotential_mV is None
    assert r.cell_voltage_V == 1.6
    assert r.test_type == "unknown"
    with pytest.raises(ValidationError):
        PerformanceRow(citekey="x", row_id="x#1", overpotential_mV="~80")


def test_config_defaults_match_data_model() -> None:
    c = LibraryConfig()
    assert c.library.format_version == 1
    assert c.ingest.title_duplicate_threshold == 0.90
    assert [s.id for s in c.note.sections][:2] == ["summary", "problem_conclusion"]
    assert len(c.note.sections) == 7
    assert c.acquire.daily_limit == 50
    with pytest.raises(ValidationError):
        LibraryConfig.model_validate({"bogus": {}})
