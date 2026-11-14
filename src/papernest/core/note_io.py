"""笔记文件的读写（DATA_MODEL 第 3 节）。输出确定：同一份 Note 永远写出相同字节。"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.library import atomic_write
from papernest.core.models import Note, Paper, Section, SectionCfg

_RISKY_CHARS = set(':,#[]{}"')
_RISKY_FIRST = set("-?:,[]{}#&*!|>'\"%@`")
_ESCAPE_EXTRA = {"\x7f": "\\u007f", "\x85": "\\u0085", " ": "\\u2028", " ": "\\u2029"}


def _err(message: str, **details: Any) -> PaperNestError:
    return PaperNestError(ErrorCode.NOTE_INVALID, message, details)


# ---- 解析 ----


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        raise _err("笔记缺少 frontmatter（首行应为 ---）")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise _err("frontmatter 没有结束的 ---")


def _split_sections(body: str, sections_cfg: list[SectionCfg]) -> list[Section]:
    raw: list[tuple[str, list[str]]] = [("", [])]
    for line in body.split("\n"):
        if line.startswith("## ") and line[3:].strip():
            raw.append((line[3:].strip(), []))
        else:
            raw[-1][1].append(line)

    by_heading = {c.heading: c.id for c in sections_cfg}
    order = {c.id: i for i, c in enumerate(sections_cfg)}
    seen: set[str] = set()
    preamble: list[Section] = []
    known: list[Section] = []
    unknown: list[Section] = []
    for heading, lines in raw:
        content = "\n".join(lines)
        if heading == "":
            if content.strip():
                preamble.append(Section(id=None, heading="", content=content))
            continue
        sid = by_heading.get(heading)
        if sid is not None and sid not in seen:
            seen.add(sid)
            known.append(Section(id=sid, heading=heading, content=content))
        else:
            unknown.append(Section(id=None, heading=heading, content=content))
    known.sort(key=lambda s: order[s.id] if s.id is not None else 0)
    return preamble + known + unknown


def parse_note(text: str, sections_cfg: list[SectionCfg]) -> Note:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    fm_text, body = _split_frontmatter(text)
    try:
        data = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        raise _err(f"frontmatter 不是合法的 YAML：{e}") from e
    if not isinstance(data, dict):
        raise _err("frontmatter 必须是键值映射")
    try:
        paper = Paper.model_validate(data)
        return Note(paper=paper, sections=_split_sections(body, sections_cfg))
    except ValidationError as e:
        problems = [
            {"field": ".".join(str(x) for x in err["loc"]), "message": err["msg"]}
            for err in e.errors()
        ]
        summary = "; ".join(f"{p['field']}: {p['message']}" for p in problems)
        raise _err(f"笔记校验失败：{summary}", errors=problems) from e


# ---- 输出 ----


def _quote(s: str) -> str:
    out = json.dumps(s, ensure_ascii=False)
    for ch, esc in _ESCAPE_EXTRA.items():
        out = out.replace(ch, esc)
    return out


def _scalar(s: str, flow: bool) -> str:
    """能安全地写成无引号就不加引号，否则一律双引号；写出的值必须能原样读回。"""
    risky = (
        s == ""
        or s != s.strip()
        or any(c in _RISKY_CHARS for c in s)
        or s[0] in _RISKY_FIRST
        or any(ord(c) < 32 or ord(c) in (0x7F, 0x85, 0x2028, 0x2029, 0xFEFF) for c in s)
    )
    if not risky:
        try:
            probe = yaml.safe_load(f"[{s}]") if flow else yaml.safe_load(f"k: {s}")
            ok = probe == ([s] if flow else {"k": s})
        except yaml.YAMLError:
            ok = False
        if ok:
            return s
    return _quote(s)


def _value(v: Any) -> str:
    """返回 `key:` 之后的部分（含前导空格），null 时为空串。"""
    if v is None:
        return ""
    if isinstance(v, Enum):
        v = v.value
    if isinstance(v, datetime):
        return " " + v.isoformat(timespec="seconds")
    if isinstance(v, bool):
        raise TypeError("frontmatter 不应出现布尔值")
    if isinstance(v, int):
        return f" {v}"
    if isinstance(v, str):
        return " " + _scalar(v, flow=False)
    if isinstance(v, list):
        return " [" + ", ".join(_scalar(str(x), flow=True) for x in v) + "]"
    raise TypeError(f"无法输出 frontmatter 值：{v!r}")


def dump_note(note: Note) -> str:
    lines = ["---"]
    for key in Paper.model_fields:
        lines.append(f"{key}:{_value(getattr(note.paper, key))}")
    lines.append("---")
    out = "\n".join(lines) + "\n"
    body = note.body_markdown()
    if body:
        out += "\n" + body
    return out


# ---- 文件 ----


def read_note(path: Path, sections_cfg: list[SectionCfg]) -> Note:
    path = Path(path)
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise _err(f"笔记不是合法的 UTF-8：{path.name}", path=str(path)) from e
    try:
        note = parse_note(text, sections_cfg)
    except PaperNestError as e:
        e.details.setdefault("path", str(path))
        raise
    if note.paper.citekey != path.stem:
        raise _err(
            f"citekey 与文件名不符：{note.paper.citekey} ≠ {path.stem}",
            path=str(path),
            citekey=note.paper.citekey,
        )
    return note


def write_note(path: Path, note: Note) -> None:
    atomic_write(Path(path), dump_note(note))
