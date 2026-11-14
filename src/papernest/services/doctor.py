"""库体检：13 项检查（规格 02-core 第 9 节）。只读，不修改库。"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from papernest.core.errors import PaperNestError
from papernest.core.models import CITEKEY_RE, Note, PerformanceRow
from papernest.core.note_io import read_note
from papernest.core.textsim import find_similar_titles
from papernest.services.context import ServiceContext

Severity = Literal["error", "warning", "info"]

_FILE_RE = re.compile(r"^(?P<stem>.+)\.[a-z0-9]+$")
_SI_STEM_RE = re.compile(r"^(?P<ck>.+)_SI(?P<n>\d*)$")
# [[citekey]]、[[citekey|别名]]、[[citekey#小节]]
_TOPIC_REF_RE = re.compile(r"\[\[([^\[\]|#]+?)\s*(?:[|#][^\[\]]*)?\]\]")
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


class DoctorIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Severity
    citekeys: list[str] = Field(default_factory=list)
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    summary: dict[str, int]
    issues: list[DoctorIssue]


def _listing(path: Any) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(p.name for p in path.iterdir() if p.is_file() and not p.name.startswith("."))


def check(ctx: ServiceContext) -> DoctorReport:
    lib = ctx.library
    issues: list[DoctorIssue] = []

    def add(
        code: str,
        severity: Severity,
        message: str,
        citekeys: list[str] | None = None,
        **data: Any,
    ) -> None:
        issues.append(
            DoctorIssue(
                code=code,
                severity=severity,
                citekeys=sorted(set(citekeys or [])),
                message=message,
                data=data,
            )
        )

    all_keys = lib.list_citekeys()
    key_set = set(all_keys)

    # 1. note_invalid —— 逐篇解析，不依赖索引，才能给出具体原因
    notes: dict[str, Note] = {}
    for ck in all_keys:
        if not CITEKEY_RE.fullmatch(ck):
            add("note_invalid", "error", f"笔记文件名不是合法的 citekey：{ck}.md", [ck])
            continue
        try:
            notes[ck] = read_note(lib.note_path(ck), lib.config.note.sections)
        except PaperNestError as e:
            add("note_invalid", "error", f"笔记无法解析：{e.message}", [ck])

    # papers/ 只遍历一次：citekey 不含下划线，所以 `<ck>` 与 `<ck>_SI<n>` 不会混淆
    mains: dict[str, list[str]] = defaultdict(list)
    sis: dict[str, list[str]] = defaultdict(list)
    orphan_papers: list[str] = []
    for name in _listing(lib.papers_dir):
        m = _FILE_RE.match(name)
        stem = m.group("stem") if m else None
        if stem is not None and stem in key_set:
            mains[stem].append(name)
            continue
        si = _SI_STEM_RE.match(stem) if stem is not None else None
        if si is not None and si.group("ck") in key_set:
            sis[si.group("ck")].append(name)
            continue
        orphan_papers.append(name)

    # 2. missing_main_file
    missing_main = [ck for ck in notes if not mains.get(ck)]
    if missing_main:
        add("missing_main_file", "warning", f"{len(missing_main)} 篇笔记没有主文件", missing_main)

    # 3. orphan_file
    orphan_texts = [
        n for n in _listing(lib.root / "text") if not (n.endswith(".txt") and n[:-4] in key_set)
    ]
    if orphan_papers or orphan_texts:
        add(
            "orphan_file",
            "warning",
            f"{len(orphan_papers)} 个 papers/ 文件、{len(orphan_texts)} 个 text/ 文件"
            "不属于任何笔记",
            papers=orphan_papers,
            text=orphan_texts,
        )

    # 4. si_mismatch
    for ck, note in notes.items():
        listed = set(note.paper.si_files)
        on_disk = set(sis.get(ck, []))
        absent = sorted(listed - on_disk)
        unlisted = sorted(on_disk - listed)
        if absent or unlisted:
            parts: list[str] = []
            if absent:
                parts.append(f"列出但不存在：{', '.join(absent)}")
            if unlisted:
                parts.append(f"存在但未列出：{', '.join(unlisted)}")
            add(
                "si_mismatch",
                "warning",
                f"{ck} 的 si_files 与磁盘不一致（{'；'.join(parts)}）",
                [ck],
                listed_missing=absent,
                unlisted_on_disk=unlisted,
            )

    # 5. missing_text
    text_names = set(_listing(lib.root / "text"))
    no_text = [ck for ck in notes if mains.get(ck) and f"{ck}.txt" not in text_names]
    if no_text:
        add("missing_text", "info", f"{len(no_text)} 篇有主文件但没有 text/ 全文缓存", no_text)

    # 6. duplicate_doi
    by_doi: dict[str, list[str]] = defaultdict(list)
    for ck, note in notes.items():
        if note.paper.doi:
            by_doi[note.paper.doi].append(ck)
    for doi, cks in sorted(by_doi.items()):
        if len(cks) > 1:
            add("duplicate_doi", "warning", f"DOI {doi} 被多篇使用", cks, doi=doi)

    # 7. similar_titles
    threshold = lib.config.ingest.title_duplicate_threshold
    titles = [(ck, n.paper.title) for ck, n in notes.items()]
    for a, b, score in find_similar_titles(titles, threshold):
        add(
            "similar_titles",
            "warning",
            f"{a} 与 {b} 标题相似度 {score:.2f}",
            [a, b],
            similarity=round(score, 4),
        )

    # 8. 词表
    tag_users: dict[str, list[str]] = defaultdict(list)
    journal_users: dict[str, list[str]] = defaultdict(list)
    for ck, note in notes.items():
        for tag in note.paper.tags:
            if not ctx.vocab.normalize_tag(tag)[1]:
                tag_users[tag].append(ck)
        j = note.paper.journal
        if j and ctx.vocab.journal(j) is None:
            journal_users[j].append(ck)
    for tag, cks in sorted(tag_users.items()):
        add("tag_not_in_vocab", "warning", f"标签「{tag}」不在词表中", cks, tag=tag)
    for j, cks in sorted(journal_users.items()):
        add("journal_not_in_vocab", "warning", f"期刊「{j}」不在期刊表中", cks, journal=j)
    for kind, names in ctx.vocab.unreviewed_items().items():
        if names:
            add(
                "unreviewed_vocab",
                "info",
                f"词表里有 {len(names)} 个待确认的{'标签' if kind == 'tags' else '期刊'}",
                kind=kind,
                names=names,
            )

    # 9. characterization_unmapped
    unmapped: dict[str, list[str]] = defaultdict(list)
    for ck, note in notes.items():
        for raw in note.paper.characterization_unmapped:
            unmapped[raw].append(ck)
    if unmapped:
        counts = {
            k: len(v) for k, v in sorted(unmapped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        }
        add(
            "characterization_unmapped",
            "warning",
            f"{len(counts)} 种表征写法未映射到词表",
            [ck for v in unmapped.values() for ck in v],
            counts=counts,
        )

    # 10. dangling_related
    for ck, note in notes.items():
        bad = [r for r in note.paper.related if r not in key_set]
        if bad:
            add(
                "dangling_related",
                "warning",
                f"{ck} 的 related 指向不存在的笔记：{', '.join(bad)}",
                [ck],
                missing=bad,
            )

    # 11. dangling_topic_ref —— 只认形如 citekey 的 [[x]]，避免把主题间的链接当成悬空
    topics_dir = lib.root / "topics"
    if topics_dir.is_dir():
        for p in sorted(topics_dir.glob("*.md")):
            text = p.read_text(encoding="utf-8-sig", errors="replace")
            refs = {
                r
                for r in (m.group(1).strip() for m in _TOPIC_REF_RE.finditer(text))
                if CITEKEY_RE.fullmatch(r) and r not in key_set
            }
            if refs:
                add(
                    "dangling_topic_ref",
                    "warning",
                    f"{p.name} 引用了不存在的笔记：{', '.join(sorted(refs))}",
                    sorted(refs),
                    topic=p.name,
                )

    # 12. performance_orphan（顺带报告读不进来的行）
    perf = lib.root / "data" / "performance.csv"
    if perf.is_file():
        orphan_rows: dict[str, list[str]] = defaultdict(list)
        invalid_rows: list[int] = []
        with perf.open(encoding="utf-8-sig", newline="") as f:
            for i, row in enumerate(csv.DictReader(f), start=2):
                try:
                    pr = PerformanceRow.model_validate(row)
                except ValidationError:
                    invalid_rows.append(i)
                    continue
                if pr.citekey not in key_set:
                    orphan_rows[pr.citekey].append(pr.row_id)
        if orphan_rows:
            add(
                "performance_orphan",
                "warning",
                f"performance.csv 有 {sum(map(len, orphan_rows.values()))} 行指向不存在的笔记",
                list(orphan_rows),
                row_ids=[r for v in orphan_rows.values() for r in v],
            )
        if invalid_rows:
            add(
                "performance_invalid",
                "warning",
                f"performance.csv 有 {len(invalid_rows)} 行格式不合法",
                lines=invalid_rows,
            )

    # 13. inbox_pending
    pending = _listing(lib.root / "inbox")
    if pending:
        add("inbox_pending", "info", f"inbox 里有 {len(pending)} 个待处理文件", count=len(pending))

    issues.sort(key=lambda i: (_SEVERITY_ORDER[i.severity], i.code, i.citekeys))
    summary = {s: sum(1 for i in issues if i.severity == s) for s in ("error", "warning", "info")}
    return DoctorReport(ok=summary["error"] == 0, summary=summary, issues=issues)
