from __future__ import annotations

import json
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from papernest import __version__
from papernest.interfaces.cli import commands

app = typer.Typer(help="PaperNest：文献精读笔记库", no_args_is_help=True, add_completion=False)


@app.callback()
def _root(
    ctx: typer.Context,
    library: Annotated[
        Path | None,
        typer.Option("--library", help="文献库路径；缺省读环境变量 PAPERNEST_LIBRARY"),
    ] = None,
) -> None:
    ctx.obj = {"library": library}


commands.register(app)


@app.command()
def version(
    as_json: Annotated[bool, typer.Option("--json", help="以 JSON 输出")] = False,
) -> None:
    """显示版本号。"""
    if as_json:
        typer.echo(json.dumps({"version": __version__}))
    else:
        typer.echo(f"PaperNest {__version__}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="监听地址")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="监听端口")] = 8765,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="不自动打开浏览器")] = False,
) -> None:
    """启动本机 HTTP 服务（API 与前端）。"""
    import uvicorn

    from papernest.interfaces.api.app import create_app

    url = f"http://{host}:{port}"
    if not no_browser:
        # 稍后打开，等服务先起来
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    typer.echo(f"服务地址：{url}")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
