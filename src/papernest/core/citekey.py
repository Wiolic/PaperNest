"""citekey 的校验、生成与撞名后缀（DATA_MODEL 第 4 节）。"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.models import CITEKEY_RE

UNKNOWN = "unknown"

# LEGACY_MAP R03 点名的元素符号与领域缩写；是否使用由调用方（词表/配置）决定
DEFAULT_PRESERVE = frozenset(
    {"Ir", "Co", "Ru", "Ti", "Mn", "Ni", "Pt"}
    | {"OER", "HER", "PEM", "PEMWE", "AEM", "AEMFC", "TEM", "SEM", "DFT"}
    | {"AIMD", "XPS", "EELS", "STEM", "MEA", "CCM"}
)


def validate(citekey: str) -> None:
    if not CITEKEY_RE.fullmatch(citekey):
        raise PaperNestError(
            ErrorCode.CITEKEY_INVALID, f"citekey 格式不合法：{citekey!r}", {"citekey": citekey}
        )


def condense_words(words: Iterable[str], preserve: Collection[str] = ()) -> str:
    """规范大小写后用连字符连接。

    词内的非字母数字字符当作分隔；`preserve` 里的词（不区分大小写匹配）按给定写法输出，
    其余首字母大写、其余小写。没有任何可用词时返回 `Paper`。
    """
    keep = {p.casefold(): p for p in preserve}
    out: list[str] = []
    for word in words:
        for part in re.split(r"[^A-Za-z0-9]+", word):
            if not part:
                continue
            out.append(keep.get(part.casefold()) or part[:1].upper() + part[1:].lower())
    return "-".join(out) or "Paper"


def _clean_abbr(abbr: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", abbr or "") or UNKNOWN


def _clean_title(title: str) -> str:
    s = re.sub(r"\s+", "-", title.strip())
    s = re.sub(r"[^A-Za-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "Paper"


def build(year: int | None, journal_abbr: str | None, condensed_title: str) -> str:
    """年份或期刊缺失时写 `unknown`，结果总能通过 `validate`。"""
    year_part = UNKNOWN if year is None else f"{year:04d}"
    ck = f"{year_part}-{_clean_abbr(journal_abbr)}-{_clean_title(condensed_title)}"
    validate(ck)
    return ck


def uniquify(base: str, existing: Collection[str]) -> str:
    """撞名追加 -2、-3……；比较不区分大小写（Windows 文件系统大小写不敏感）。"""
    taken = {e.casefold() for e in existing}
    if base.casefold() not in taken:
        return base
    n = 2
    while f"{base}-{n}".casefold() in taken:
        n += 1
    return f"{base}-{n}"
