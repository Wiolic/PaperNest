# 阶段 1 规格：工程脚手架

执行档位：Sonnet。前置阅读：`CLAUDE.md`、`docs/ARCHITECTURE.md` 第 2、3、8 节。

目标：一个能安装、能跑测试、CI 通过的空壳工程。**不写任何业务逻辑。**

## 0. 环境准备（本机现状：有 git 2.55、Python 3.12、gh；没有 uv、没有 Node）

1. 安装 uv：`winget install astral-sh.uv`（失败则用官方 PowerShell 安装脚本）。安装前告知用户。
2. 安装 Node LTS：`winget install OpenJS.NodeJS.LTS`。安装前告知用户。
3. 若仓库没有 git 身份，问用户要用的名字和邮箱，用 `git config`（仓库级）设置，不要自己猜。

## 1. 要建立的文件

| 路径 | 内容 |
|---|---|
| `pyproject.toml` | 项目名 `papernest`，版本 `0.1.0.dev0`，`requires-python = ">=3.11"`，构建后端 hatchling，src 布局，入口 `papernest = "papernest.interfaces.cli.main:app"`。运行依赖：pydantic≥2、pyyaml、rapidfuzz、httpx、typer、fastapi、uvicorn、filelock、keyring。可选组：`llm`（openai）、`pdf`（pypdfium2、python-docx）、`export`（openpyxl、python-docx、citeproc-py）、`word`（pywin32; 仅 win32）、`acquire`（playwright）、`mcp`（mcp）、`all`（以上全部）。dev 组：pytest、pytest-cov、ruff、pyright、respx。 |
| `uv.lock` | `uv lock` 生成，提交 |
| `.gitignore` | Python、Node、`src/papernest/web_dist/`、`.venv/`、`dist/`、`*.db`、`.papernest/` |
| `.gitattributes` | `* text=auto eol=lf` |
| `LICENSE` | MIT，版权人写 `PaperNest contributors` |
| `README.md` | 十行以内：一句话简介、"开发中"声明、开发环境三条命令 |
| `CHANGELOG.md` | Keep a Changelog 格式，只有 Unreleased |
| `ruff.toml` | 行宽 100，目标 py311，规则集 E、F、I、UP、B、SIM；启用 format |
| `pyrightconfig.json` | `typeCheckingMode: basic`，include `src` |
| `src/papernest/__init__.py` | `__version__` |
| `src/papernest/__main__.py` | 调 CLI |
| `src/papernest/{core,adapters,services,prompts,interfaces,migrate}/__init__.py` | 空包 |
| `src/papernest/core/errors.py` | `PaperNestError(Exception)` 基类，带 `code: str`、`message: str`、`details: dict`；先定义 `ErrorCode` 字符串枚举：`library_not_found`、`library_format_too_new`、`note_invalid`、`citekey_invalid`、`citekey_not_found`、`citekey_exists`、`locked`、`llm_output_invalid`、`external_service`、`not_supported`、`internal` |
| `src/papernest/interfaces/cli/main.py` | Typer app；命令 `version`（`--json` 时输出 `{"version": "..."}`）；`serve --host 127.0.0.1 --port 8765 --no-browser` |
| `src/papernest/interfaces/api/app.py` | `create_app() -> FastAPI`；`GET /api/v1/health` 返回 `{"status":"ok","version":…}`；`PaperNestError` 的统一异常处理器；若 `web_dist/index.html` 存在则挂载静态文件到 `/` |
| `web/` | `npm create vite@latest`（react-ts 模板）后精简：一个页面，调用 `/api/v1/health` 并显示版本号。`vite.config.ts`：`build.outDir = "../src/papernest/web_dist"`，开发时把 `/api` 代理到 `127.0.0.1:8765`。CSS 变量写入配色：`--bg:#F4F1EC; --blue-deep:#5B7C99; --blue:#7B93AB; --blue-light:#C4D1DB; --card:#E6E9E4; --text:#3B4A54`。 |
| `tests/unit/test_smoke.py` | 版本号可导入；`ErrorCode` 值唯一 |
| `tests/integration/test_api_health.py` | 用 FastAPI TestClient 测 `/api/v1/health` |
| `tests/integration/test_cli.py` | 用 Typer CliRunner 测 `version --json` 输出合法 JSON |
| `tests/unit/test_layering.py` | 静态检查 import 方向：扫描 `src/papernest/**.py` 的 import 语句，断言 `core` 不 import `adapters`/`services`/`interfaces`，`adapters` 不 import `services`/`interfaces`，`services` 不 import `interfaces` |
| `.github/workflows/ci.yml` | 触发：push、pull_request。矩阵：`windows-latest`、`ubuntu-latest` × Python 3.11、3.12。步骤：setup-uv → `uv sync --all-extras --dev` → `uv run ruff check .` → `uv run ruff format --check .` → `uv run pyright` → `uv run pytest`。另一个 job：setup-node → `npm ci` → `npm run build`（在 `web/`）。Linux 上 `word` 组因平台标记自动跳过。 |

## 2. 不做的事

- 不建 GitHub 远程仓库、不 push（需要用户决定仓库名和公开性，收尾时问）。
- 不写任何 core 模块的实现。
- 不引入前端 UI 库、路由、状态管理（阶段 9 再定）。

## 3. 验收清单

```
uv sync --all-extras --dev          成功
uv run ruff check .                 无报错
uv run ruff format --check .        无改动
uv run pyright                      0 errors
uv run pytest                       全部通过
uv run papernest version --json    输出 {"version": "0.1.0.dev0"}
cd web && npm ci && npm run build   成功，src/papernest/web_dist/index.html 存在
uv run papernest serve --no-browser   启动后浏览器访问 http://127.0.0.1:8765 能看到版本号
```

全部通过后提交，按 `CLAUDE.md` 的收尾流程结束会话。
