from __future__ import annotations

import random
import time

import pytest

from papernest.core import textsim
from papernest.core.textsim import (
    find_similar_titles,
    is_missing_doi,
    is_missing_title,
    normalize_filename,
    normalize_title,
    strip_html,
    title_similarity,
)


def test_normalize_title() -> None:
    assert normalize_title("  Hello,   WORLD! (2024): a-b_c ") == "hello world 2024 a b c"
    assert normalize_title("太阳能，燃料电池") == "太阳能 燃料电池"
    assert normalize_title("") == ""


def test_title_similarity_basics() -> None:
    a = "Hybrid membrane design for ion transport in aqueous system"
    b = "Hybrid membrane design for ion transport in aqueous systems"
    assert title_similarity(a, b) > 0.9
    assert title_similarity(a, a.upper()) == 1.0
    assert title_similarity(a, "Something entirely different") < 0.5
    assert title_similarity("", "") == 0.0
    assert title_similarity("???", "abc") == 0.0


def test_dedupe_title_normalization() -> None:
    # 标点、大小写、HTML 标签、全角字符不影响相似度
    assert title_similarity("IrO<sub>2</sub> for OER: a study", "IrO2 for oer – a study") == 1.0
    assert title_similarity("ＡＢＣ catalysts", "abc catalysts") == 1.0


def test_crossref_title_html_tags_stripped_on_ingest() -> None:
    assert strip_html("Ir<i>O</i><sub>2</sub>  &amp;  Ru\n<b>x</b>") == "IrO2 & Ru x"
    assert strip_html("a < b and c > d") == "a < b and c > d"


def test_missing_doi_placeholders_single_definition() -> None:
    for v in ["N/A", "n/a", "NA", "unknown", "None", "null", "", "  ", "Not Available", '"N/A"']:
        assert is_missing_doi(v), v
    assert is_missing_doi(None)
    assert not is_missing_doi("10.1000/xyz")
    assert is_missing_title("Untitled") and is_missing_title(None)
    assert not is_missing_title("A real title")
    assert "n/a" in textsim.MISSING_DOI_VALUES


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("Paper Title SI", "paper title"),
        ("paper-title-supplementary-information", "paper title information"),
        ("xxx-sup-0001-suppmat", "xxx 0001"),
        ("mmc1", ""),
        ("Some_Article_moesm3_esm", "some article"),
        ("论文标题_SI", "论文标题"),
    ],
)
def test_normalize_filename_strips_si_markers(stem: str, expected: str) -> None:
    assert normalize_filename(stem) == expected


def test_is_si_token() -> None:
    assert textsim.is_si_token("ESI") and textsim.is_si_token("mmc12")
    assert textsim.is_si_token("MOESM2")
    assert not textsim.is_si_token("silicon") and not textsim.is_si_token("mmc")


def test_find_similar_titles_small() -> None:
    items = [
        ("a", "Hybrid membrane design for ion transport in aqueous system"),
        ("b", "Layered oxide transport properties"),
        ("c", "Hybrid membrane design for ion transport in aqueous systems"),
        ("d", ""),
        ("e", "hybrid membrane design for ion transport in aqueous systems"),
    ]
    out = find_similar_titles(items, 0.9)
    assert [(x, y) for x, y, _ in out] == [("c", "e"), ("a", "c"), ("a", "e")] or {
        (x, y) for x, y, _ in out
    } == {("a", "c"), ("a", "e"), ("c", "e")}
    assert out[0][2] == 1.0
    assert all(s >= 0.9 for _, _, s in out)
    assert find_similar_titles([("a", "x")], 0.9) == []
    assert find_similar_titles([], 0.9) == []


def test_find_similar_titles_matches_bruteforce() -> None:
    rng = random.Random(7)
    words = ["catalyst", "oxide", "membrane", "iridium", "water", "acid", "stable", "layer"]
    items = []
    for i in range(120):
        t = " ".join(rng.choice(words) for _ in range(rng.randint(2, 6)))
        if rng.random() < 0.3:
            t += rng.choice(["s", "", " x"])
        items.append((f"k{i:03d}", t))
    for thr in (0.6, 0.9):
        got = {(a, b): s for a, b, s in find_similar_titles(items, thr)}
        want = {}
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                s = title_similarity(items[i][1], items[j][1])
                if s >= thr:
                    want[(items[i][0], items[j][0])] = s
        assert set(got) == set(want)
        for k in want:
            assert got[k] == pytest.approx(want[k])


def test_find_similar_titles_ten_thousand_is_fast() -> None:
    rng = random.Random(1)
    vocab = [f"w{rng.randrange(3000)}x" for _ in range(3000)]
    items = [
        (f"k{i}", " ".join(rng.choice(vocab) for _ in range(rng.randint(6, 14))))
        for i in range(10_000)
    ]
    items += [("dupA", items[5][1] + "s"), ("dupB", items[77][1])]
    t0 = time.perf_counter()
    out = find_similar_titles(items, 0.9)
    elapsed = time.perf_counter() - t0
    assert elapsed < 10, f"{elapsed:.1f}s"
    pairs = {(a, b) for a, b, _ in out}
    assert ("k5", "dupA") in pairs and ("k77", "dupB") in pairs
