"""核心数据模型。所有校验规则集中在这里（DATA_MODEL 第 2、3、4、6 节）。"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CITEKEY_RE = re.compile(r"^(\d{4}|unknown)-[A-Za-z0-9]+-[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperType(StrEnum):
    COMPUTATIONAL = "computational"
    EXPERIMENTAL = "experimental"
    COMBINED = "combined"
    REVIEW = "review"


class Status(StrEnum):
    UNREAD = "unread"
    SKIMMED = "skimmed"
    READ = "read"


class EntryType(StrEnum):
    ARTICLE = "article"
    REVIEW = "review"
    PREPRINT = "preprint"
    BOOK = "book"
    THESIS = "thesis"
    OTHER = "other"


def normalize_doi(raw: str | None) -> str | None:
    """去前缀、转小写、去空白；空串返回 None。"""
    if raw is None:
        return None
    s = raw.strip()
    changed = True
    while changed:
        changed = False
        for p in _DOI_PREFIXES:
            if s.lower().startswith(p):
                s = s[len(p) :].strip()
                changed = True
    s = s.lower()
    return s or None


class Paper(_Model):
    """笔记 frontmatter；字段声明顺序即写出顺序。"""

    citekey: str
    title: str
    authors: list[str]
    year: int | None = Field(strict=True, ge=1800, le=2100)
    journal: str | None
    doi: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    entry_type: EntryType
    type: PaperType | None
    tags: list[str]
    keywords: list[str]
    methods: str
    characterization: list[str]
    characterization_unmapped: list[str]
    system: str
    status: Status
    rating: int | None = Field(strict=True, ge=1, le=5)
    related: list[str]
    si_files: list[str]
    added: datetime

    @field_validator("citekey")
    @classmethod
    def _citekey(cls, v: str) -> str:
        if not CITEKEY_RE.fullmatch(v):
            raise ValueError(f"citekey 格式不合法: {v!r}")
        return v

    @field_validator("doi")
    @classmethod
    def _doi(cls, v: str | None) -> str | None:
        return normalize_doi(v)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = re.sub(r"\s*[\r\n]+\s*", " ", v).strip()
        if not v:
            raise ValueError("title 不能为空")
        return v

    @field_validator("added")
    @classmethod
    def _added(cls, v: datetime) -> datetime:
        # 秒精度的本地时间（naive）；带时区的换成本地时间
        if v.tzinfo is not None:
            v = v.astimezone().replace(tzinfo=None)
        return v.replace(microsecond=0)


class SectionCfg(_Model):
    id: str
    heading: str


class Section(_Model):
    """正文小节。`id` 为 None 表示配置里没有的自定义小节；`heading=""` 表示前置内容。"""

    id: str | None = None
    heading: str
    content: str = ""

    @field_validator("heading")
    @classmethod
    def _heading(cls, v: str) -> str:
        return re.sub(r"\s*[\r\n]+\s*", " ", v).strip()

    @field_validator("content")
    @classmethod
    def _content(cls, v: str) -> str:
        # 去掉首尾的空白行（保留首行缩进），统一 LF
        lines = v.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(line.rstrip() if not line.strip() else line for line in lines)


class Note(_Model):
    paper: Paper
    sections: list[Section] = Field(default_factory=list)

    def section(self, id: str) -> str:
        for s in self.sections:
            if s.id == id:
                return s.content
        return ""

    def body_markdown(self) -> str:
        """frontmatter 之后的正文；非空时以单个换行结尾。"""
        blocks: list[str] = []
        for s in self.sections:
            if s.heading == "":
                blocks.append(s.content + "\n" if s.content else "")
                continue
            blocks.append(f"## {s.heading}\n" + (s.content + "\n" if s.content else ""))
        blocks = [b for b in blocks if b]
        return "\n".join(blocks)


class Attachment(_Model):
    path: Path
    kind: Literal["main", "si"]


PERFORMANCE_COLUMNS: tuple[str, ...] = (
    "citekey",
    "row_id",
    "test_type",
    "reaction",
    "electrolyte",
    "temperature_C",
    "catalyst_loading_mg_cm2",
    "current_density_ref_mA_cm2",
    "overpotential_mV",
    "cell_voltage_V",
    "tafel_slope_mV_dec",
    "stability_duration_h",
    "degradation_rate",
    "other_metrics",
    "source_location",
)


class PerformanceRow(_Model):
    citekey: str
    row_id: str
    test_type: Literal["half-cell", "MEA", "full-cell", "unknown"] = "unknown"
    reaction: str | None = None
    electrolyte: str | None = None
    temperature_C: float | None = None
    catalyst_loading_mg_cm2: float | None = None
    current_density_ref_mA_cm2: float | None = None
    overpotential_mV: float | None = None
    cell_voltage_V: float | None = None
    tafel_slope_mV_dec: float | None = None
    stability_duration_h: float | None = None
    degradation_rate: float | None = None
    other_metrics: str | None = None
    source_location: str | None = None

    @field_validator(
        "temperature_C",
        "catalyst_loading_mg_cm2",
        "current_density_ref_mA_cm2",
        "overpotential_mV",
        "cell_voltage_V",
        "tafel_slope_mV_dec",
        "stability_duration_h",
        "degradation_rate",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, v: Any) -> Any:
        # CSV 里的空单元格读成空串
        if isinstance(v, str) and not v.strip():
            return None
        return v


# ---- papernest.toml ----


class LibraryMeta(_Model):
    format_version: int = 1
    name: str = "我的文献库"


class LlmCfg(_Model):
    base_url: str = "https://api.deepseek.com"
    model_extract: str = "deepseek-v4-flash"
    model_summarize: str = "deepseek-v4-pro"
    max_concurrency: int = 4
    timeout_seconds: int = 120
    max_fulltext_chars: int = 200000


class IngestCfg(_Model):
    skip_non_journal: bool = True
    title_duplicate_threshold: float = 0.90
    si_filename_threshold: float = 0.82
    si_filename_min_chars: int = 10
    si_orphan_auto_threshold: float = 0.85
    si_orphan_report_threshold: float = 0.55
    crossref_title_threshold: float = 0.90


def _default_sections() -> list[SectionCfg]:
    return [
        SectionCfg(id="summary", heading="三句话总结"),
        SectionCfg(id="problem_conclusion", heading="研究问题与核心结论"),
        SectionCfg(id="method_points", heading="方法要点"),
        SectionCfg(id="key_results", heading="关键图表与数据"),
        SectionCfg(id="relevance", heading="与我课题的关联"),
        SectionCfg(id="caveats", heading="质疑与局限"),
        SectionCfg(id="further_reading", heading="值得追的参考文献"),
    ]


class NoteCfg(_Model):
    language: str = "zh"
    readable_wrap: int = 60
    sections: list[SectionCfg] = Field(default_factory=_default_sections)


class NetworkCfg(_Model):
    contact_email: str = ""


class AcquireCfg(_Model):
    min_interval_seconds: int = 20
    daily_limit: int = 50


class LibraryConfig(_Model):
    library: LibraryMeta = Field(default_factory=LibraryMeta)
    llm: LlmCfg = Field(default_factory=LlmCfg)
    ingest: IngestCfg = Field(default_factory=IngestCfg)
    note: NoteCfg = Field(default_factory=NoteCfg)
    network: NetworkCfg = Field(default_factory=NetworkCfg)
    acquire: AcquireCfg = Field(default_factory=AcquireCfg)
