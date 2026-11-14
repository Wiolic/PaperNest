"""ServiceContext：服务函数的第一个参数，持有打开的库、索引、状态库、词表与适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from papernest.core.index import Index
from papernest.core.library import Library
from papernest.core.state import State
from papernest.core.vocab import Vocab


@dataclass
class ServiceContext:
    library: Library
    index: Index
    state: State
    vocab: Vocab
    # 适配器在阶段 3 以后以 Protocol 注入；本阶段一律为 None
    llm: object | None = None
    crossref: object | None = None
    openalex: object | None = None
    unpaywall: object | None = None
    pdf_text: object | None = None
    browser: object | None = None

    @classmethod
    def open(cls, root: Path) -> ServiceContext:
        library = Library.open(root)
        return cls(
            library=library,
            index=Index(library),
            state=State(library),
            vocab=Vocab.load(library.root / "vocab"),
        )

    def close(self) -> None:
        self.index.close()
        self.state.close()
