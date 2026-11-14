# PaperTrail 2.0 开发约定

文献精读笔记库软件。本仓库只有代码和文档，不含任何文献数据。

## 每次会话开始先读

1. `docs/STATUS.md`：现在做到哪、上次留下什么。
2. 本次任务对应的 `docs/specs/NN-*.md`。
3. 规格里点名的 `docs/ARCHITECTURE.md`、`docs/DATA_MODEL.md` 章节。

`docs/PLAN.md` 是总路线图；`docs/LEGACY_MAP.md` 是旧系统功能与回归用例对照。

## 红线

- 旧库 `D:\Desktop\Reference\PaperTrail` 及 `D:\Desktop\Reference` 下其他文件夹：**只读**。不新增、不修改、不删除。
- 不读取、不打印任何密钥。旧库的 `scripts/.local_config.json` 与 `.claude/` 不要打开。
- 真实文献数据（PDF、笔记、迁移报告）不进 git。测试只用 `tests/fixtures/` 里的虚构样例。
- 不复制旧脚本的代码。旧系统只是需求来源。
- 不 push、不建远程仓库、不发版，除非用户在当次对话里明确要求。

## 三档分工

| 档位 | 模型 | 做什么 |
|---|---|---|
| 架构 | Opus | 写与改 `docs/specs/`、`ARCHITECTURE.md`、`DATA_MODEL.md`；阶段验收 |
| 执行 | Sonnet | 按规格写代码与测试 |
| 杂务 | Haiku | 样例数据、文档、跑命令并整理报告 |

- 执行档遇到规格没写清或互相矛盾的地方：选最保守的做法继续，并在 `STATUS.md` 的"待架构档决定"里记一笔；**不要自行修改** `DATA_MODEL.md` 和 `ARCHITECTURE.md`。
- 读大量文件、批量机械修改、生成样例数据这类耗 token 的活，派给更低一档的子代理。

## 代码约定

- 分层与依赖方向见 `docs/ARCHITECTURE.md` 第 2 节，`tests/unit/test_layering.py` 强制检查。
- 业务逻辑只写在 `core/` 与 `services/`。入口层（api、cli、mcp）只做参数与输出。
- 修改库的服务函数成对提供 `plan_*`（预览）与 `apply_*`（执行）。
- 写文件只通过 `Library.atomic_write`；删除只通过 `Library.trash`；按 citekey 找文件只通过 `Library` 的方法。
- 对外访问（网络、LLM、Word、浏览器）只在 `adapters/` 与 `services/word`，测试里一律替身，不真的触网。
- 错误用 `core.errors.PaperTrailError` 及其 `ErrorCode`。
- 公开函数带类型标注。注释只写"为什么"，用中文或英文均可，标识符用英文。
- 面向用户的文字（CLI 输出、API 错误信息、界面）默认中文。

## 命令

```
uv sync --all-extras --dev      建环境
uv run pytest                   测试
uv run ruff check . --fix       检查
uv run ruff format .            格式化
uv run pyright                  类型检查
uv run papertrail --help        运行 CLI
cd web && npm run dev           前端开发服务器
cd web && npm run build         前端构建到 src/papertrail/web_dist
```

## 提交

- 小步提交，一次提交一件事。格式 `<范围>: <做了什么>`，范围取模块名（`core`、`ingest`、`web`、`docs`、`ci` …）。
- 提交前必须：pytest 全过、ruff 无报错、pyright 无报错。

## 会话收尾（每次都做）

1. 跑一遍测试与检查。
2. 提交。
3. 更新 `docs/STATUS.md`：完成了什么、没完成什么、踩了什么坑、待架构档决定的问题。
4. 在回复末尾给出**下一步的可复制指令**，写明：用哪一档模型、在哪个目录开对话、读哪份规格、做到哪里为止。

上下文用过一半而本阶段未完成时，在一个干净的提交点提前收尾，给出"续做"指令。宁可多开一次对话，不要在上下文吃紧时硬撑。
