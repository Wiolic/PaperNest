"""标题与文件名的归一化和相似度。全系统只有这一份实现（ARCHITECTURE 第 4 节）。"""

from __future__ import annotations

import html
import re
import unicodedata

import numpy as np
from rapidfuzz import fuzz, process

# LEGACY_MAP R05：缺失值占位集合，全系统只在这里定义一份（小写比较）
MISSING_DOI_VALUES = frozenset(
    {"n/a", "na", "unknown", "none", "null", "", "not available", "not found", "not provided"}
)
MISSING_TITLE_VALUES = frozenset(
    {"unknown", "n/a", "na", "none", "null", "", "untitled", "not available", "not found"}
)

# LEGACY_MAP R02：SI 标记词；另有 Elsevier 的 mmc\d+ 与 Springer/Nature 的 moesm\d+
SI_MARKERS = frozenset(
    {"si", "esi", "esm", "sup", "supp", "suppmat", "supporting", "supplementary", "supplemental"}
)
SI_TOKEN_RE = re.compile(r"^(?:mmc\d+|moesm\d+)$")

_CHUNK = 500
_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")
_NON_WORD_RE = re.compile(r"[\W_]+")


def is_missing_doi(doi: str | None) -> bool:
    return doi is None or doi.strip().strip("\"'").lower() in MISSING_DOI_VALUES


def is_missing_title(title: str | None) -> bool:
    return title is None or title.strip().strip("\"'").lower() in MISSING_TITLE_VALUES


def strip_html(s: str) -> str:
    """去掉 `<i>`、`<sub>` 一类标签与 HTML 实体，折叠空白（Crossref 标题常带）。"""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", s))).strip()


def normalize_title(s: str) -> str:
    """去 HTML 标签、NFKC、casefold，标点一律视作空白后压缩。"""
    s = unicodedata.normalize("NFKC", strip_html(s)).casefold()
    return _NON_WORD_RE.sub(" ", s).strip()


def title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return float(fuzz.ratio(na, nb)) / 100


def is_si_token(token: str) -> bool:
    t = token.lower()
    return t in SI_MARKERS or bool(SI_TOKEN_RE.match(t))


def normalize_filename(stem: str) -> str:
    """去 SI 标记词后再归一化。切词用 `[\\W_]+`（旧实现是 `[^a-z0-9]+`，会把中文文件名切光）。"""
    tokens = [t for t in _NON_WORD_RE.split(unicodedata.normalize("NFKC", stem).casefold()) if t]
    return normalize_title(" ".join(t for t in tokens if not is_si_token(t)))


def find_similar_titles(
    items: list[tuple[str, str]], threshold: float
) -> list[tuple[str, str, float]]:
    """返回相似度 ≥ threshold 的成对条目 (key_a, key_b, 相似度)，a 在输入中先于 b。

    按分数降序、再按键排序。用 `cdist` 分块（每块 500 行对全部）多线程比较，
    1 万条规模约 1 秒；分块是为了把内存压在几十 MB。
    """
    entries = [(key, normalize_title(title)) for key, title in items]
    idx = [i for i, (_, n) in enumerate(entries) if n]
    norms = [entries[i][1] for i in idx]
    if len(norms) < 2:
        return []
    out: list[tuple[int, int, float]] = []
    for start in range(0, len(norms), _CHUNK):
        block = process.cdist(
            norms[start : start + _CHUNK],
            norms,
            scorer=fuzz.ratio,
            score_cutoff=threshold * 100,
            dtype=np.float32,
            workers=-1,
        )
        rows, cols = np.nonzero(block)
        for r, c in zip(rows.tolist(), cols.tolist(), strict=True):
            if start + r < c:  # 只取上三角，每对一次
                out.append((idx[start + r], idx[c], float(block[r, c]) / 100))
    out.sort(key=lambda t: (-t[2], t[0], t[1]))
    return [(entries[a][0], entries[b][0], sc) for a, b, sc in out]
