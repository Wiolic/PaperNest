"""只读 CLI 命令：library init/info、paper list/show、index rebuild、doctor。

入口层只做参数解析、调用服务、格式化输出；业务逻辑都在 core 与 services。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.index import SearchQuery
from papernest.core.library import Library
from papernest.core.models import PaperType, Status
from papernest.core.note_io import read_note
from papernest.services import doctor as doctor_service
from papernest.services.context import ServiceContext

JsonOpt = Annotated[bool, typer.Option("--json", help="以 JSON 输出（stdout 只有一个 JSON 文档）")]
LibraryOpt = Annotated[
    Path | None,
    typer.Option("--library", help="文献库路径；缺省读环境变量 PAPERNEST_LIBRARY"),
]

library_app = typer.Typer(help="文献库管理", no_args_is_help=True)
paper_app = typer.Typer(help="文献条目", no_args_is_help=True)
index_app = typer.Typer(help="索引", no_args_is_help=True)


# ---- 公共 ----


def _dump(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _emit(obj: Any, as_json: bool, text: Callable[[], str]) -> None:
    typer.echo(_dump(obj) if as_json else text())


@contextmanager
def _guard(as_json: bool) -> Iterator[None]:
    """把可预期错误转成退出码 1 与统一的错误输出。"""
    try:
        yield
    except PaperNestError as e:
        if as_json:
            typer.echo(
                _dump({"error": {"code": e.code, "message": e.message, "details": e.details}})
            )
        else:
            typer.echo(f"错误：{e.message}", err=True)
        raise typer.Exit(1) from e


def _library_root(ctx: typer.Context, local: Path | None) -> Path:
    obj: dict[str, Any] = ctx.obj or {}
    root = local or obj.get("library") or os.environ.get("PAPERNEST_LIBRARY")
    if not root:
        raise PaperNestError(
            ErrorCode.LIBRARY_NOT_FOUND,
            "未指定文献库：请用 --library <路径> 或设置环境变量 PAPERNEST_LIBRARY。",
        )
    return Path(root)


@contextmanager
def _context(ctx: typer.Context, local: Path | None) -> Iterator[ServiceContext]:
    sc = ServiceContext.open(_library_root(ctx, local))
    try:
        yield sc
    finally:
        sc.close()


# ---- library ----


@library_app.command("init")
def library_init(
    path: Annotated[Path, typer.Argument(help="新库的目录")],
    name: Annotated[str, typer.Option("--name", help="库的名称")] = "我的文献库",
    as_json: JsonOpt = False,
) -> None:
    """在 <路径> 创建一个空的文献库。"""
    with _guard(as_json):
        lib = Library.create(path, name)
        info = {"root": str(lib.root.resolve()), "name": lib.config.library.name}
        _emit(info, as_json, lambda: f"已创建文献库「{info['name']}」：{info['root']}")


@library_app.command("info")
def library_info(ctx: typer.Context, library: LibraryOpt = None, as_json: JsonOpt = False) -> None:
    """显示库的基本信息。"""
    with _guard(as_json), _context(ctx, library) as sc:
        lib = sc.library
        info = {
            "root": str(lib.root.resolve()),
            "name": lib.config.library.name,
            "format_version": lib.config.library.format_version,
            "papers": len(lib.list_citekeys()),
            "vocab": {
                "tags": len(sc.vocab.tags),
                "journals": len(sc.vocab.journals),
                "characterization": len(sc.vocab.methods),
            },
        }

        def text() -> str:
            v = info["vocab"]
            return "\n".join(
                [
                    f"名称：{info['name']}",
                    f"位置：{info['root']}",
                    f"格式版本：{info['format_version']}",
                    f"文献数：{info['papers']}",
                    f"词表：标签 {v['tags']}、期刊 {v['journals']}、"
                    f"表征方法 {v['characterization']}",
                ]
            )

        _emit(info, as_json, text)


# ---- paper ----


class SortKey(StrEnum):
    ADDED_DESC = "added_desc"
    YEAR_DESC = "year_desc"
    TITLE = "title"
    RELEVANCE = "relevance"


@paper_app.command("list")
def paper_list(
    ctx: typer.Context,
    library: LibraryOpt = None,
    as_json: JsonOpt = False,
    text: Annotated[
        str | None, typer.Option("--text", help="全文检索（标题、作者、关键词、正文）")
    ] = None,
    fulltext: Annotated[bool, typer.Option("--fulltext", help="同时检索 text/ 全文缓存")] = False,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="含任一标签，可重复")] = None,
    tag_all: Annotated[
        list[str] | None, typer.Option("--tag-all", help="同时含全部标签，可重复")
    ] = None,
    journal: Annotated[list[str] | None, typer.Option("--journal", help="期刊，可重复")] = None,
    top_only: Annotated[bool, typer.Option("--top-only", help="只看顶刊")] = False,
    year_from: Annotated[int | None, typer.Option("--year-from")] = None,
    year_to: Annotated[int | None, typer.Option("--year-to")] = None,
    paper_type: Annotated[
        list[PaperType] | None, typer.Option("--type", help="论文类型，可重复")
    ] = None,
    status: Annotated[
        list[Status] | None, typer.Option("--status", help="阅读状态，可重复")
    ] = None,
    has_pdf: Annotated[
        bool | None, typer.Option("--has-pdf/--no-pdf", help="有 / 无主文件")
    ] = None,
    sort: Annotated[SortKey, typer.Option("--sort", help="排序")] = SortKey.ADDED_DESC,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 50,
) -> None:
    """按条件列出文献。"""
    with _guard(as_json), _context(ctx, library) as sc:
        sc.index.sync()
        result = sc.index.search(
            SearchQuery(
                text=text,
                include_fulltext=fulltext,
                tags_any=tag or [],
                tags_all=tag_all or [],
                journals=journal or [],
                top_journals_only=top_only,
                year_from=year_from,
                year_to=year_to,
                types=paper_type or [],
                status=status or [],
                has_pdf=has_pdf,
                sort=sort.value,
                offset=offset,
                limit=limit,
            )
        )

        def render() -> str:
            lines = [f"共 {result.total} 篇（库内 {result.library_total} 篇）"]
            for r in result.items:
                lines.append(f"{r.citekey}  [{r.year or '----'}]  {r.title}")
            return "\n".join(lines)

        _emit(result, as_json, render)


@paper_app.command("show")
def paper_show(
    ctx: typer.Context,
    citekey: Annotated[str, typer.Argument(help="文献的 citekey")],
    library: LibraryOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """显示一篇文献的元数据与笔记正文。"""
    with _guard(as_json), _context(ctx, library) as sc:
        path = sc.library.note_path(citekey)
        if not path.is_file():
            raise PaperNestError(
                ErrorCode.CITEKEY_NOT_FOUND, f"找不到文献：{citekey}", {"citekey": citekey}
            )
        note = read_note(path, sc.library.config.note.sections)

        def render() -> str:
            p = note.paper
            lines = [
                f"# {p.title}",
                f"citekey：{p.citekey}",
                f"作者：{'; '.join(p.authors) or '（无）'}",
                f"年份：{p.year or '（无）'}　期刊：{p.journal or '（无）'}",
                f"DOI：{p.doi or '（无）'}",
                f"标签：{', '.join(p.tags) or '（无）'}",
                f"状态：{p.status}　评分：{p.rating or '（无）'}",
            ]
            body = note.body_markdown()
            if body:
                lines += ["", body.rstrip()]
            return "\n".join(lines)

        _emit(note, as_json, render)


# ---- index ----


@index_app.command("rebuild")
def index_rebuild(ctx: typer.Context, library: LibraryOpt = None, as_json: JsonOpt = False) -> None:
    """丢弃并重建索引。"""
    with _guard(as_json), _context(ctx, library) as sc:
        report = sc.index.rebuild()

        def render() -> str:
            lines = [f"索引已重建：新增 {len(report.added)} 篇，解析失败 {len(report.errors)} 篇"]
            lines += [f"  {e.citekey}：{e.error}" for e in report.errors]
            return "\n".join(lines)

        _emit(report, as_json, render)


# ---- doctor ----


def doctor(ctx: typer.Context, library: LibraryOpt = None, as_json: JsonOpt = False) -> None:
    """检查库的完整性与一致性（只读）；有 error 级问题时退出码为 1。"""
    with _guard(as_json), _context(ctx, library) as sc:
        report = doctor_service.check(sc)

        def render() -> str:
            s = report.summary
            lines = [f"体检结果：{s['error']} 个错误，{s['warning']} 个警告，{s['info']} 条提示"]
            for i in report.issues:
                lines.append(f"[{i.severity}] {i.code}：{i.message}")
                if i.citekeys:
                    lines.append(f"    涉及：{', '.join(i.citekeys)}")
            return "\n".join(lines)

        _emit(report, as_json, render)
        if not report.ok:
            raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.add_typer(library_app, name="library")
    app.add_typer(paper_app, name="paper")
    app.add_typer(index_app, name="index")
    app.command("doctor")(doctor)
