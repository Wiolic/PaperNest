from __future__ import annotations

from pathlib import Path

import pytest

from papernest.core.errors import PaperNestError
from papernest.core.library import Library
from papernest.core.note_io import read_note
from papernest.core.vocab import Vocab, normalize_journal_name

from ..conftest import SMALL


@pytest.fixture
def vocab() -> Vocab:
    return Vocab.load(SMALL / "vocab")


def test_sample_vocab_leaves_exactly_one_tag_unlisted(vocab: Vocab) -> None:
    lib = Library.open(SMALL)
    unlisted = set()
    for ck in lib.list_citekeys():
        for tag in read_note(lib.note_path(ck), lib.config.note.sections).paper.tags:
            if not vocab.normalize_tag(tag)[1]:
                unlisted.add((ck, tag))
    assert unlisted == {("2023-Joule-Solar-Fuel-Cell", "未收录标签")}


def test_sample_vocab_covers_journals_and_characterization(vocab: Vocab) -> None:
    lib = Library.open(SMALL)
    for ck in lib.list_citekeys():
        p = read_note(lib.note_path(ck), lib.config.note.sections).paper
        if p.journal:
            assert vocab.journal(p.journal) is not None, p.journal
        for m in p.characterization:
            assert vocab.normalize_characterization(m)[1], m
        for m in p.characterization_unmapped:
            assert not vocab.normalize_characterization(m)[1], m


def test_sample_vocab_roundtrip_is_byte_stable(tmp_path: Path) -> None:
    import shutil

    d = tmp_path / "vocab"
    shutil.copytree(SMALL / "vocab", d)
    Vocab.load(d).save()
    for name in ("tags.yaml", "journals.yaml", "characterization.yaml"):
        assert (d / name).read_bytes() == (SMALL / "vocab" / name).read_bytes()


def test_load_missing_dir_gives_empty_vocab(tmp_path: Path) -> None:
    v = Vocab.load(tmp_path / "nope")
    assert v.tags == [] and v.journals == [] and v.methods == []
    assert v.prefixes == ["in situ", "operando", "ex situ"]


@pytest.mark.parametrize("bad", ["tags: 3", "- a", "tags:\n  - {name: x, bogus: 1}", "tags: [: ["])
def test_load_invalid_file_raises(tmp_path: Path, bad: str) -> None:
    (tmp_path / "tags.yaml").write_text(bad, encoding="utf-8")
    with pytest.raises(PaperNestError) as ei:
        Vocab.load(tmp_path)
    assert ei.value.code == "config_invalid"


def test_load_invalid_prefixes_raises(tmp_path: Path) -> None:
    (tmp_path / "characterization.yaml").write_text("prefixes: 5\n", encoding="utf-8")
    with pytest.raises(PaperNestError):
        Vocab.load(tmp_path)


def test_empty_yaml_file_is_empty_vocab(tmp_path: Path) -> None:
    (tmp_path / "tags.yaml").write_text("", encoding="utf-8")
    assert Vocab.load(tmp_path).tags == []


def test_normalize_tag(vocab: Vocab) -> None:
    assert vocab.normalize_tag("battery") == ("电池", True)
    assert vocab.normalize_tag("  单原子催化 ") == ("单原子", True)
    assert vocab.normalize_tag("ELECTROCATALYSIS") == ("电催化", True)
    assert vocab.normalize_tag(" 新标签 ") == ("新标签", False)


def test_add_tag(vocab: Vocab, tmp_path: Path) -> None:
    vocab.vocab_dir = tmp_path
    vocab.add_tag("新标签")
    assert vocab.normalize_tag("新标签") == ("新标签", True)
    vocab.add_tag("新标签")  # 重复添加无副作用
    assert [t.name for t in vocab.tags].count("新标签") == 1
    assert vocab.unreviewed_items()["tags"] == ["新标签"]
    vocab.save()
    assert Vocab.load(tmp_path).unreviewed_items()["tags"] == ["新标签"]
    with pytest.raises(PaperNestError):
        vocab.add_tag("  ")


@pytest.mark.parametrize(
    "raw, norm",
    [
        ("The Journal of  Physics", "journal of physics"),
        ("  Science & Engineering ", "science and engineering"),
        ("Science and Engineering", "science and engineering"),
        ("THE NATURE", "nature"),
    ],
)
def test_normalize_journal_name(raw: str, norm: str) -> None:
    assert normalize_journal_name(raw) == norm


def test_journal_lookup_by_alias_and_case(vocab: Vocab) -> None:
    for name in ("J. Am. Chem. Soc.", "journal of the american chemical society", "The JACS"):
        entry = vocab.journal(name)
        assert entry is not None and entry.abbr == "JACS"
    assert vocab.journal("Unknown Journal") is None
    assert vocab.journal(None) is None
    assert vocab.journal_abbr("Nat. Commun.") == "NatCommun"
    assert vocab.journal_abbr("???") is None


def test_journal_abbr_canonical_mapping(vocab: Vocab) -> None:
    # ACIE 一律映射到 AngewChemIntEd，两种写法不并存
    assert vocab.journal_abbr("ACIE") == "AngewChemIntEd"
    assert vocab.journal_abbr("Angew. Chem. Int. Ed.") == "AngewChemIntEd"
    assert vocab.journal_key("ACIE") == vocab.journal_key("Angewandte Chemie International Edition")


def test_top_journals_match_normalizes_journal_names(vocab: Vocab) -> None:
    for name in (
        "Angewandte Chemie",
        "Angew. Chem. Int. Ed.",
        "J. Am. Chem. Soc.",
        "journal of the american chemical society ",
        "the nature",
    ):
        assert vocab.is_top_journal(name), name
    assert not vocab.is_top_journal("ACS Nano")
    assert not vocab.is_top_journal("Nowhere Letters")
    assert not vocab.is_top_journal(None)


def test_journal_key_for_unknown_journal_is_normalized_raw(vocab: Vocab) -> None:
    assert vocab.journal_key("The  New   Journal") == "new journal"


def test_add_journal(vocab: Vocab, tmp_path: Path) -> None:
    vocab.vocab_dir = tmp_path
    vocab.add_journal("Brand New Letters", "BNL")
    assert vocab.journal_abbr("brand new letters") == "BNL"
    assert vocab.unreviewed_items()["journals"] == ["Brand New Letters"]
    vocab.add_journal("Brand New Letters", "BNL")  # 同名同缩写：无操作
    assert len(vocab.journals) == 10


def test_add_journal_abbr_conflicts(vocab: Vocab) -> None:
    with pytest.raises(PaperNestError) as ei:
        vocab.add_journal("Other Letters", "jacs")  # 缩写被占用，不区分大小写
    assert ei.value.code == "vocab_conflict"
    with pytest.raises(PaperNestError) as ei:
        vocab.add_journal("J. Am. Chem. Soc.", "JAmChemSoc")  # 同一期刊只能有一个缩写
    assert ei.value.code == "vocab_conflict"
    with pytest.raises(PaperNestError):
        vocab.add_journal("Bad Abbr", "B-A")
    with pytest.raises(PaperNestError):
        vocab.add_journal("  ", "OK")


def test_abbr_does_not_shadow_other_journal_alias() -> None:
    from papernest.core.vocab import JournalEntry

    v = Vocab(
        Path("."),
        [],
        [
            JournalEntry(name="Alpha", abbr="Beta"),
            JournalEntry(name="Beta Journal", abbr="BJ", aliases=["Beta"]),
        ],
        [],
        [],
    )
    entry = v.journal("Beta")
    assert entry is not None and entry.name == "Beta Journal"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("XAS", ("XAS", True)),
        ("xafs", ("XAS", True)),
        ("scanning tunneling microscopy", ("STM", True)),
        ("in situ Raman", ("in situ Raman", True)),
        ("In Situ XRD", ("in situ XRD", True)),
        ("in-situ Raman", ("in situ Raman", True)),
        ("insitu-Raman", ("in situ Raman", True)),
        ("insitu Raman", ("in situ Raman", True)),
        ("operando-pxrd", ("operando XRD", True)),
        ("Operando  拉曼", ("operando Raman", True)),
        ("ex situ XPS", ("ex situ XPS", True)),
        ("in situ wacky probe", ("in situ wacky probe", False)),
        ("wacky probe", ("wacky probe", False)),
        ("in situ", ("in situ", False)),
        ("unmapped:J-V measurements", ("J-V measurements", False)),
    ],
)
def test_characterization_prefix_variants_normalized(
    vocab: Vocab, raw: str, expected: tuple[str, bool]
) -> None:
    assert vocab.normalize_characterization(raw) == expected


def test_in_situ_and_operando_never_merged(vocab: Vocab) -> None:
    assert (
        vocab.normalize_characterization("operando Raman")[0]
        != (vocab.normalize_characterization("in situ Raman")[0])
    )


def test_unmapped_prefix_not_in_frontmatter(vocab: Vocab) -> None:
    name, mapped = vocab.normalize_characterization("unmapped:EQE")
    assert not mapped and not name.startswith("unmapped:")
