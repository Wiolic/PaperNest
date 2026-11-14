"""库的目录布局、打开与创建、原子写、写锁、回收区、格式迁移（ARCHITECTURE 第 4、10 节）。"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import threading
import time
import tomllib
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from pydantic import ValidationError

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.models import CITEKEY_RE, PERFORMANCE_COLUMNS, LibraryConfig

FORMAT_VERSION = 1
CONFIG_NAME = "papernest.toml"

# 登记 v→v+1 的迁移函数；v1 时为空（DATA_MODEL 第 10 节）
MIGRATIONS: dict[int, Callable[[Library], None]] = {}

_DIRS = (
    "notes",
    "papers",
    "text",
    "topics",
    "data",
    "vocab",
    "inbox",
    "exports",
    ".papernest/cache",
    ".papernest/trash",
    ".papernest/backups",
    ".papernest/browser",
    ".papernest/logs",
)

_DEFAULT_VOCAB = {
    "tags.yaml": "tags: []\n",
    "journals.yaml": "journals: []\n",
    "characterization.yaml": 'prefixes: ["in situ", "operando", "ex situ"]\nmethods: []\n',
    "discovery.yaml": "fields: []\n",
}

_REPLACE_RETRIES = 8


def atomic_write(path: Path, data: str | bytes) -> None:
    """同目录写临时文件 → flush + fsync → os.replace。文本一律 UTF-8、LF。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        if isinstance(data, str):
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        else:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        # Windows 上目标文件被杀毒软件或索引器短暂占用时 replace 会失败，重试几次
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(0.02 * (attempt + 1))
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, list):
        if v and all(isinstance(x, dict) for x in v):
            rows = ",\n".join(f"  {_toml_inline(x)}" for x in v)
            return f"[\n{rows},\n]"
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"无法写成 TOML: {v!r}")


def _toml_inline(d: dict[str, Any]) -> str:
    return "{ " + ", ".join(f"{k} = {_toml_value(v)}" for k, v in d.items()) + " }"


def render_config(config: LibraryConfig) -> str:
    parts: list[str] = []
    for name, table in config.model_dump().items():
        lines = [f"[{name}]"]
        lines += [f"{k} = {_toml_value(v)}" for k, v in table.items()]
        parts.append("\n".join(lines))
    return "\n\n".join(parts) + "\n"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-") or "op"


class Library:
    def __init__(self, root: Path, config: LibraryConfig) -> None:
        self.root: Path = Path(root)
        self.config: LibraryConfig = config
        self._lock = FileLock(str(self.root / ".papernest" / "lock"))
        self._trash_mutex = threading.Lock()

    # ---- 打开与创建 ----

    @classmethod
    def open(cls, root: Path) -> Library:
        root = Path(root)
        cfg_path = root / CONFIG_NAME
        if not cfg_path.is_file():
            raise PaperNestError(
                ErrorCode.LIBRARY_NOT_FOUND,
                f"找不到文献库（缺少 {CONFIG_NAME}）：{root}",
                {"root": str(root)},
            )
        try:
            raw = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))
            config = LibraryConfig.model_validate(raw)
        except (tomllib.TOMLDecodeError, ValidationError, UnicodeDecodeError) as e:
            raise PaperNestError(
                ErrorCode.CONFIG_INVALID,
                f"{CONFIG_NAME} 无法解析：{e}",
                {"root": str(root)},
            ) from e
        version = config.library.format_version
        if version > FORMAT_VERSION:
            raise PaperNestError(
                ErrorCode.LIBRARY_FORMAT_TOO_NEW,
                f"库格式版本 {version} 高于本软件支持的 {FORMAT_VERSION}，请升级软件。",
                {"library_version": version, "supported": FORMAT_VERSION},
            )
        lib = cls(root, config)
        if version < FORMAT_VERSION:
            lib.upgrade()
        return lib

    @classmethod
    def create(cls, root: Path, name: str) -> Library:
        root = Path(root)
        if (root / CONFIG_NAME).exists():
            raise PaperNestError(
                ErrorCode.LIBRARY_EXISTS, f"该位置已有文献库：{root}", {"root": str(root)}
            )
        config = LibraryConfig()
        config.library.name = name
        config.library.format_version = FORMAT_VERSION
        root.mkdir(parents=True, exist_ok=True)
        for d in _DIRS:
            (root / d).mkdir(parents=True, exist_ok=True)
        lib = cls(root, config)
        for fname, text in _DEFAULT_VOCAB.items():
            p = root / "vocab" / fname
            if not p.exists():
                atomic_write(p, text)
        profile = root / "profile.md"
        if not profile.exists():
            atomic_write(profile, "# 课题背景\n\n（在此描述你的研究课题，入库时会提供给 LLM。）\n")
        perf = root / "data" / "performance.csv"
        if not perf.exists():
            atomic_write(perf, ",".join(PERFORMANCE_COLUMNS) + "\n")
        lib.save_config()
        return lib

    def save_config(self) -> None:
        self.atomic_write(self.root / CONFIG_NAME, render_config(self.config))

    # ---- 路径 ----

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def papers_dir(self) -> Path:
        return self.root / "papers"

    @property
    def state_dir(self) -> Path:
        return self.root / ".papernest"

    def _check_citekey(self, citekey: str) -> None:
        # 同时挡住路径穿越
        if not CITEKEY_RE.fullmatch(citekey):
            raise PaperNestError(
                ErrorCode.CITEKEY_INVALID, f"citekey 格式不合法：{citekey!r}", {"citekey": citekey}
            )

    def note_path(self, citekey: str) -> Path:
        self._check_citekey(citekey)
        return self.notes_dir / f"{citekey}.md"

    def text_path(self, citekey: str) -> Path:
        self._check_citekey(citekey)
        return self.root / "text" / f"{citekey}.txt"

    def _papers_listing(self) -> list[str]:
        if not self.papers_dir.is_dir():
            return []
        return sorted(p.name for p in self.papers_dir.iterdir() if p.is_file())

    def main_file(self, citekey: str) -> Path | None:
        """papers/<ck>.<ext> 精确匹配；`X-2.pdf` 不属于 `X`。有多个时优先 pdf。"""
        self._check_citekey(citekey)
        pat = re.compile(rf"^{re.escape(citekey)}\.[a-z0-9]+$")
        hits = [n for n in self._papers_listing() if pat.match(n)]
        if not hits:
            return None
        hits.sort(key=lambda n: (not n.endswith(".pdf"), n))
        return self.papers_dir / hits[0]

    def si_files(self, citekey: str) -> list[Path]:
        """papers/<ck>_SI.<ext>、_SI2 …，按序号排序（无序号视为 1）。"""
        self._check_citekey(citekey)
        pat = re.compile(rf"^{re.escape(citekey)}_SI(\d*)\.[a-z0-9]+$")
        found: list[tuple[int, str]] = []
        for n in self._papers_listing():
            m = pat.match(n)
            if m:
                found.append((int(m.group(1)) if m.group(1) else 1, n))
        found.sort()
        return [self.papers_dir / n for _, n in found]

    def files_of(self, citekey: str) -> list[Path]:
        """该文献现存的全部文件：笔记、主文件、SI、全文缓存。"""
        out: list[Path] = []
        note = self.note_path(citekey)
        if note.is_file():
            out.append(note)
        main = self.main_file(citekey)
        if main is not None:
            out.append(main)
        out.extend(self.si_files(citekey))
        text = self.text_path(citekey)
        if text.is_file():
            out.append(text)
        return out

    def list_citekeys(self) -> list[str]:
        """以 notes/*.md 为准，排序；不校验名字格式（交给 doctor 报告）。"""
        if not self.notes_dir.is_dir():
            return []
        return sorted(
            p.stem
            for p in self.notes_dir.iterdir()
            if p.suffix == ".md" and not p.name.startswith(".")
        )

    # ---- 写入 ----

    @contextlib.contextmanager
    def write_lock(self, timeout: float = 30) -> Iterator[None]:
        """库级写锁；同一线程可重入，不同线程与进程互斥。超时抛 locked。"""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            ctx = self._lock.acquire(timeout=timeout)
        except Timeout as e:
            raise PaperNestError(
                ErrorCode.LOCKED, "文献库正被另一个操作占用，请稍后重试。", {"timeout": timeout}
            ) from e
        with ctx:
            yield

    def atomic_write(self, path: Path, data: str | bytes) -> None:
        atomic_write(path, data)

    # ---- 回收区 ----

    def _rel(self, path: Path) -> Path:
        try:
            return Path(path).resolve().relative_to(self.root.resolve())
        except ValueError as e:
            raise PaperNestError(
                ErrorCode.INTERNAL, f"路径不在库内：{path}", {"path": str(path)}
            ) from e

    def trash(self, paths: list[Path], operation: str) -> Path:
        """把文件移入 .papernest/trash/<时间戳>-<operation>/，保留相对路径；返回回收目录。"""
        rels: list[tuple[Path, Path]] = []
        for p in paths:
            rel = self._rel(p)
            if rel.parts and rel.parts[0] == ".papernest":
                raise PaperNestError(ErrorCode.INTERNAL, f"不能回收内部文件：{p}")
            if not Path(p).exists():
                raise FileNotFoundError(str(p))
            rels.append((Path(p), rel))
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = self.state_dir / "trash" / f"{stamp}-{_slug(operation)}"
        with self._trash_mutex:
            target = base
            n = 2
            while target.exists():
                target = base.with_name(f"{base.name}-{n}")
                n += 1
            target.mkdir(parents=True)
        for src, rel in rels:
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        return target

    def restore(self, trash_dir: Path) -> list[Path]:
        """把回收目录里的文件放回原相对路径；任一目标已存在则整体拒绝。"""
        trash_dir = Path(trash_dir)
        trash_root = (self.state_dir / "trash").resolve()
        if not trash_dir.resolve().is_relative_to(trash_root) or trash_dir.resolve() == trash_root:
            raise PaperNestError(ErrorCode.INTERNAL, f"不是回收目录：{trash_dir}")
        if not trash_dir.is_dir():
            raise FileNotFoundError(str(trash_dir))
        moves = [
            (f, self.root / f.relative_to(trash_dir))
            for f in sorted(trash_dir.rglob("*"))
            if f.is_file()
        ]
        clash = [str(d) for _, d in moves if d.exists()]
        if clash:
            raise PaperNestError(
                ErrorCode.FILE_EXISTS, "原位置已有同名文件，无法还原。", {"paths": clash}
            )
        restored: list[Path] = []
        for src, dest in moves:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            restored.append(dest)
        shutil.rmtree(trash_dir, ignore_errors=True)
        return restored

    # ---- 格式迁移 ----

    def backup(self) -> Path:
        """迁移前备份 notes/ 与 state.db 到 .papernest/backups/<时间戳>/。"""
        base = self.state_dir / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = base
        n = 2
        while dest.exists():
            dest = base.with_name(f"{base.name}-{n}")
            n += 1
        dest.mkdir(parents=True)
        if self.notes_dir.is_dir():
            shutil.copytree(self.notes_dir, dest / "notes")
        state_db = self.state_dir / "state.db"
        if state_db.is_file():
            shutil.copy2(state_db, dest / "state.db")
        return dest

    def upgrade(self) -> None:
        version = self.config.library.format_version
        if version >= FORMAT_VERSION:
            return
        missing = [v for v in range(version, FORMAT_VERSION) if v not in MIGRATIONS]
        if missing:
            raise PaperNestError(
                ErrorCode.NOT_SUPPORTED,
                f"缺少从格式 v{missing[0]} 升级的迁移函数。",
                {"from": version, "to": FORMAT_VERSION},
            )
        with self.write_lock():
            self.backup()
            for v in range(version, FORMAT_VERSION):
                MIGRATIONS[v](self)
                self.config.library.format_version = v + 1
                self.save_config()
