"""词表：标签、期刊、表征方法的加载、保存与归一化（DATA_MODEL 第 5 节）。

discovery.yaml 不在此处理（属于查新服务）；`save()` 也不会碰它。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from papernest.core.errors import ErrorCode, PaperNestError
from papernest.core.library import atomic_write

DEFAULT_PREFIXES = ("in situ", "operando", "ex situ")
_ABBR_RE = re.compile(r"^[A-Za-z0-9]+$")


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TagEntry(_Entry):
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    unreviewed: bool = False


class JournalEntry(_Entry):
    name: str
    abbr: str
    aliases: list[str] = Field(default_factory=list)
    top: bool = False
    unreviewed: bool = False


class MethodEntry(_Entry):
    name: str
    aliases: list[str] = Field(default_factory=list)
    parent: str | None = None


def normalize_journal_name(name: str) -> str:
    """casefold、去首尾空格、去开头的 `the `、`&` 视同 `and`、连续空白压成一个空格。"""
    s = name.casefold().replace("&", " and ")
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:].strip()
    return s


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold()).strip()


class _FlowListDumper(yaml.SafeDumper):
    """标量列表用行内流式，映射与条目列表保持块式，让词表文件一条一段、别名一行。"""


def _represent_list(dumper: yaml.SafeDumper, data: list[Any]) -> yaml.Node:
    flow = all(not isinstance(x, dict | list) for x in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_FlowListDumper.add_representer(list, _represent_list)


def _dump(data: dict[str, Any]) -> str:
    return yaml.dump(
        data,
        Dumper=_FlowListDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=10**6,
    )


def _vocab_error(message: str, **details: Any) -> PaperNestError:
    return PaperNestError(ErrorCode.CONFIG_INVALID, message, details)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise _vocab_error(f"词表无法解析：{path.name}：{e}", path=str(path)) from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _vocab_error(f"词表格式不对（顶层应为映射）：{path.name}", path=str(path))
    return data


_T = TypeVar("_T", bound=BaseModel)


def _entries(path: Path, key: str, model: type[_T]) -> list[_T]:
    raw = _read_yaml(path).get(key) or []
    if not isinstance(raw, list):
        raise _vocab_error(f"{path.name} 的 {key} 应为列表", path=str(path))
    out: list[_T] = []
    for i, item in enumerate(raw):
        try:
            out.append(model.model_validate(item))
        except ValidationError as e:
            raise _vocab_error(
                f"{path.name} 第 {i + 1} 项不合法：{e}", path=str(path), index=i
            ) from e
    return out


class Vocab:
    def __init__(
        self,
        vocab_dir: Path,
        tags: list[TagEntry],
        journals: list[JournalEntry],
        prefixes: list[str],
        methods: list[MethodEntry],
    ) -> None:
        self.vocab_dir = Path(vocab_dir)
        self.tags = tags
        self.journals = journals
        self.prefixes = prefixes
        self.methods = methods
        self._reindex()

    # ---- 加载与保存 ----

    @classmethod
    def load(cls, vocab_dir: Path) -> Vocab:
        d = Path(vocab_dir)
        char = _read_yaml(d / "characterization.yaml")
        prefixes = char.get("prefixes")
        if prefixes is None:
            prefixes = list(DEFAULT_PREFIXES)
        if not isinstance(prefixes, list) or not all(isinstance(p, str) for p in prefixes):
            raise _vocab_error("characterization.yaml 的 prefixes 应为字符串列表")
        return cls(
            d,
            _entries(d / "tags.yaml", "tags", TagEntry),
            _entries(d / "journals.yaml", "journals", JournalEntry),
            list(prefixes),
            _entries(d / "characterization.yaml", "methods", MethodEntry),
        )

    def save(self) -> None:
        d = self.vocab_dir
        d.mkdir(parents=True, exist_ok=True)
        atomic_write(d / "tags.yaml", _dump({"tags": [t.model_dump() for t in self.tags]}))
        atomic_write(
            d / "journals.yaml",
            _dump({"journals": [j.model_dump() for j in self.journals]}),
        )
        atomic_write(
            d / "characterization.yaml",
            _dump(
                {
                    "prefixes": list(self.prefixes),
                    "methods": [m.model_dump() for m in self.methods],
                }
            ),
        )

    def _reindex(self) -> None:
        self._tag_map: dict[str, TagEntry] = {}
        for t in self.tags:
            for key in (t.name, *t.aliases):
                self._tag_map.setdefault(_fold(key), t)
        # 全名与别名优先于缩写，避免某期刊的缩写盖住另一期刊的别名
        self._journal_map: dict[str, JournalEntry] = {}
        for j in self.journals:
            for key in (j.name, *j.aliases):
                self._journal_map.setdefault(normalize_journal_name(key), j)
        for j in self.journals:
            self._journal_map.setdefault(normalize_journal_name(j.abbr), j)
        self._method_map: dict[str, MethodEntry] = {}
        for m in self.methods:
            for key in (m.name, *m.aliases):
                self._method_map.setdefault(_fold(key), m)
        self._prefix_res = [(p, _prefix_regex(p)) for p in self.prefixes]

    # ---- 标签 ----

    def normalize_tag(self, raw: str) -> tuple[str, bool]:
        s = raw.strip()
        entry = self._tag_map.get(_fold(s))
        if entry is not None:
            return entry.name, True
        return s, False

    def add_tag(self, name: str, unreviewed: bool = True) -> None:
        name = name.strip()
        if not name:
            raise _vocab_error("标签不能为空")
        if self.normalize_tag(name)[1]:
            return
        self.tags.append(TagEntry(name=name, unreviewed=unreviewed))
        self._reindex()

    # ---- 期刊 ----

    def journal(self, name: str | None) -> JournalEntry | None:
        if not name:
            return None
        return self._journal_map.get(normalize_journal_name(name))

    def journal_key(self, name: str) -> str:
        """索引与过滤用的期刊键：表内期刊取规范全名的归一化形式，别名因此合并。"""
        entry = self.journal(name)
        return normalize_journal_name(entry.name if entry else name)

    def journal_abbr(self, name: str | None) -> str | None:
        entry = self.journal(name)
        return entry.abbr if entry else None

    def is_top_journal(self, name: str | None) -> bool:
        entry = self.journal(name)
        return bool(entry and entry.top)

    def add_journal(self, name: str, abbr: str, unreviewed: bool = True) -> None:
        name = name.strip()
        abbr = abbr.strip()
        if not name:
            raise _vocab_error("期刊名不能为空")
        if not _ABBR_RE.fullmatch(abbr):
            raise _vocab_error(f"期刊缩写只能含字母和数字：{abbr!r}", abbr=abbr)
        existing = self.journal(name)
        if existing is not None:
            if existing.abbr == abbr:
                return
            raise PaperNestError(
                ErrorCode.VOCAB_CONFLICT,
                f"期刊「{existing.name}」已有缩写 {existing.abbr}，同一期刊只能有一个缩写",
                {"name": name, "abbr": abbr, "existing_abbr": existing.abbr},
            )
        for j in self.journals:
            if j.abbr.casefold() == abbr.casefold():
                raise PaperNestError(
                    ErrorCode.VOCAB_CONFLICT,
                    f"缩写 {abbr} 已被「{j.name}」占用",
                    {"name": name, "abbr": abbr, "owner": j.name},
                )
        self.journals.append(JournalEntry(name=name, abbr=abbr, unreviewed=unreviewed))
        self._reindex()

    # ---- 表征方法 ----

    def normalize_characterization(self, raw: str) -> tuple[str, bool]:
        s = raw.strip()
        # 旧系统遗留的 unmapped: 前缀不属于规范写法，读入时去掉
        if s.lower().startswith("unmapped:"):
            s = s[len("unmapped:") :].strip()
        prefix: str | None = None
        rest = s
        for p, rx in self._prefix_res:
            m = rx.match(s)
            if m and s[m.end() :].strip():
                prefix, rest = p, s[m.end() :].strip()
                break
        entry = self._method_map.get(_fold(rest))
        if entry is None:
            return s, False
        return (f"{prefix} {entry.name}" if prefix else entry.name), True

    def unreviewed_items(self) -> dict[str, list[str]]:
        return {
            "tags": [t.name for t in self.tags if t.unreviewed],
            "journals": [j.name for j in self.journals if j.unreviewed],
        }


def _prefix_regex(prefix: str) -> re.Pattern[str]:
    # `in situ` 也接受 `in-situ`、`insitu`、`In Situ`；前缀后须跟空格或连字符
    words = [re.escape(w) for w in prefix.split()]
    return re.compile(r"[\s\-]*".join(words) + r"[\s\-]+", re.IGNORECASE)
