from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    LIBRARY_NOT_FOUND = "library_not_found"
    LIBRARY_FORMAT_TOO_NEW = "library_format_too_new"
    NOTE_INVALID = "note_invalid"
    CITEKEY_INVALID = "citekey_invalid"
    CITEKEY_NOT_FOUND = "citekey_not_found"
    CITEKEY_EXISTS = "citekey_exists"
    LOCKED = "locked"
    LLM_OUTPUT_INVALID = "llm_output_invalid"
    EXTERNAL_SERVICE = "external_service"
    NOT_SUPPORTED = "not_supported"
    INTERNAL = "internal"


class PaperTrailError(Exception):
    """所有可预期错误的基类；入口层据 `code` 映射为退出码或 HTTP 状态。"""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: str = str(code)
        self.message: str = message
        self.details: dict[str, Any] = details or {}
