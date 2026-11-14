from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from papernest import __version__
from papernest.core.errors import ErrorCode, PaperNestError

WEB_DIST = Path(__file__).resolve().parents[2] / "web_dist"

# 错误码到 HTTP 状态的映射；未列出的按 500
_STATUS: dict[str, int] = {
    ErrorCode.LIBRARY_NOT_FOUND: 404,
    ErrorCode.CITEKEY_NOT_FOUND: 404,
    ErrorCode.CITEKEY_EXISTS: 409,
    ErrorCode.LOCKED: 423,
    ErrorCode.NOTE_INVALID: 422,
    ErrorCode.CITEKEY_INVALID: 422,
    ErrorCode.LIBRARY_FORMAT_TOO_NEW: 409,
    ErrorCode.NOT_SUPPORTED: 501,
    ErrorCode.EXTERNAL_SERVICE: 502,
    ErrorCode.LLM_OUTPUT_INVALID: 502,
}


async def _handle_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PaperNestError)
    return JSONResponse(
        status_code=_STATUS.get(exc.code, 500),
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


def create_app() -> FastAPI:
    app = FastAPI(title="PaperNest", version=__version__)
    app.add_exception_handler(PaperNestError, _handle_error)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # 最后挂载，避免盖住 /api
    if (WEB_DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app
