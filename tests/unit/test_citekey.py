from __future__ import annotations

import pytest

from papernest.core import citekey
from papernest.core.errors import PaperNestError


@pytest.mark.parametrize("ck", ["2024-JACS-Foo", "unknown-unknown-Foo-Bar", "2024-X-Foo-2"])
def test_validate_ok(ck: str) -> None:
    citekey.validate(ck)


@pytest.mark.parametrize(
    "ck", ["", "2024-JACS", "24-JACS-Foo", "2024-JA_CS-Foo", "../x-y-z", "2024-JACS-Foo."]
)
def test_validate_bad(ck: str) -> None:
    with pytest.raises(PaperNestError) as ei:
        citekey.validate(ck)
    assert ei.value.code == "citekey_invalid"


def test_condense_words() -> None:
    preserve = {"Ir", "OER", "PEM"}
    assert citekey.condense_words(["iridium", "OXIDE", "for", "oer"], preserve) == (
        "Iridium-Oxide-For-OER"
    )
    assert citekey.condense_words(["ir", "pem"], preserve) == "Ir-PEM"
    # 词内的连字符、标点当作分隔
    assert citekey.condense_words(["Single-Atom", "(Ir)", "catalysts!"], preserve) == (
        "Single-Atom-Ir-Catalysts"
    )
    assert citekey.condense_words([], preserve) == "Paper"
    assert citekey.condense_words(["!!!", "中文"]) == "Paper"
    assert "OER" in citekey.DEFAULT_PRESERVE


def test_build() -> None:
    assert citekey.build(2024, "JACS", "Ir-OER-Catalyst") == "2024-JACS-Ir-OER-Catalyst"
    assert citekey.build(None, None, "Foo") == "unknown-unknown-Foo"
    assert citekey.build(2020, "  ", "Foo") == "2020-unknown-Foo"
    assert citekey.build(2020, "Nat. Commun.", "A  b--c!") == "2020-NatCommun-A-b-c"
    assert citekey.build(2020, "J", "!!!") == "2020-J-Paper"
    with pytest.raises(PaperNestError):
        citekey.build(12345, "J", "Foo")


def test_uniquify() -> None:
    assert citekey.uniquify("A-B-C", []) == "A-B-C"
    assert citekey.uniquify("A-B-C", ["A-B-C"]) == "A-B-C-2"
    assert citekey.uniquify("A-B-C", ["A-B-C", "A-B-C-2", "A-B-C-3"]) == "A-B-C-4"
    # 不是撞名：`-2` 本身被占用但原名空闲
    assert citekey.uniquify("A-B-C", ["A-B-C-2"]) == "A-B-C"


def test_citekey_collision_case_insensitive() -> None:
    assert citekey.uniquify("2025-JACS-Ir-OER", {"2025-JACS-IR-OER"}) == "2025-JACS-Ir-OER-2"
    assert citekey.uniquify("2025-JACS-Ir-OER", {"2025-jacs-ir-oer", "2025-JACS-Ir-OER-2"}) == (
        "2025-JACS-Ir-OER-3"
    )
