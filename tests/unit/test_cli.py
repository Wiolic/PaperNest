from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from papernest.interfaces.cli.main import app

runner = CliRunner()


def _run(*args: str) -> tuple[int, str]:
    r = runner.invoke(app, list(args))
    return r.exit_code, r.output


def test_library_init_and_info(tmp_path: Path) -> None:
    target = tmp_path / "newlib"
    code, out = _run("library", "init", str(target), "--name", "测试库", "--json")
    assert code == 0 and json.loads(out)["name"] == "测试库"
    code, out = _run("--library", str(target), "library", "info", "--json")
    info = json.loads(out)
    assert code == 0 and info["papers"] == 0 and info["format_version"] == 1
    code, out = _run("library", "info", "--library", str(target))
    assert code == 0 and "测试库" in out
    # 已存在则报错
    code, out = _run("library", "init", str(target), "--json")
    assert code == 1 and json.loads(out)["error"]["code"] == "library_exists"
    code, out = _run("library", "init", str(target))
    assert code == 1


def test_no_library_specified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAPERNEST_LIBRARY", raising=False)
    code, out = _run("library", "info", "--json")
    assert code == 1 and json.loads(out)["error"]["code"] == "library_not_found"
    code, _ = _run("library", "info")
    assert code == 1


def test_library_from_env(small_lib_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERNEST_LIBRARY", str(small_lib_path))
    code, out = _run("library", "info", "--json")
    assert code == 0 and json.loads(out)["papers"] == 12


def test_paper_list_text_json(small_lib_path: Path) -> None:
    code, out = _run(
        "--library", str(small_lib_path), "paper", "list", "--text", "Nickel", "--json"
    )
    data = json.loads(out)
    assert code == 0 and data["total"] == 1
    assert data["items"][0]["citekey"] == "2023-JACS-Nickel-Catalyst-Selective"
    assert data["library_total"] == 12


def test_paper_list_filters_and_text_output(small_lib_path: Path) -> None:
    lib = str(small_lib_path)
    code, out = _run(
        "--library", lib, "paper", "list", "--tag", "电催化", "--year-from", "2022",
        "--sort", "year_desc", "--no-pdf", "--status", "unread", "--limit", "5",
    )  # fmt: skip
    assert code == 0 and out.startswith("共 ")
    code, out = _run("--library", lib, "paper", "list", "--top-only", "--has-pdf", "--json")
    assert code == 0 and json.loads(out)["total"] >= 0
    code, _ = _run("--library", lib, "paper", "list", "--type", "bogus")
    assert code != 0


def test_paper_show(small_lib_path: Path) -> None:
    lib = str(small_lib_path)
    ck = "2023-JACS-Nickel-Catalyst-Selective"
    code, out = _run("--library", lib, "paper", "show", ck, "--json")
    data = json.loads(out)
    assert code == 0 and data["paper"]["citekey"] == ck
    code, out = _run("--library", lib, "paper", "show", ck)
    assert code == 0 and ck in out and "DOI：" in out
    code, out = _run("--library", lib, "paper", "show", "2099-No-Such-Paper", "--json")
    assert code == 1 and json.loads(out)["error"]["code"] == "citekey_not_found"
    code, _ = _run("--library", lib, "paper", "show", "../evil")
    assert code == 1


def test_index_rebuild(small_lib_path: Path) -> None:
    lib = str(small_lib_path)
    code, out = _run("--library", lib, "index", "rebuild", "--json")
    data = json.loads(out)
    assert code == 0 and len(data["added"]) == 12 and data["errors"] == []
    (small_lib_path / "notes" / "2024-JACS-Broken-Note.md").write_text("oops", "utf-8")
    code, out = _run("--library", lib, "index", "rebuild")
    assert code == 0 and "解析失败 1 篇" in out and "2024-JACS-Broken-Note" in out


def test_doctor_json_and_text(small_lib_path: Path) -> None:
    lib = str(small_lib_path)
    code, out = _run("--library", lib, "doctor", "--json")
    data = json.loads(out)
    assert code == 0 and data["ok"] is True
    assert {i["code"] for i in data["issues"]} >= {"similar_titles", "tag_not_in_vocab"}
    code, out = _run("--library", lib, "doctor")
    assert code == 0 and "体检结果" in out and "涉及：" in out
    # 有 error 时退出码为 1
    (small_lib_path / "notes" / "2024-JACS-Broken-Note.md").write_text("oops", "utf-8")
    code, out = _run("--library", lib, "doctor", "--json")
    assert code == 1 and json.loads(out)["ok"] is False
