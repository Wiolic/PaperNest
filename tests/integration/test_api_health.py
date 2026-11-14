from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from papertrail import __version__
from papertrail.core.errors import ErrorCode, PaperTrailError
from papertrail.interfaces.api import app as app_module
from papertrail.interfaces.api.app import create_app


def test_health() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}


def test_error_handler_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 不挂静态目录，否则之后添加的测试路由会被 "/" 挂载盖住
    monkeypatch.setattr(app_module, "WEB_DIST", tmp_path / "missing")
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise PaperTrailError(ErrorCode.CITEKEY_NOT_FOUND, "找不到", {"citekey": "x"})

    resp = TestClient(app).get("/boom")
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "citekey_not_found", "message": "找不到", "details": {"citekey": "x"}}
    }
