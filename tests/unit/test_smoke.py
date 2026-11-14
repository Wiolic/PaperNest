import papertrail
from papertrail.core.errors import ErrorCode, PaperTrailError


def test_version_importable() -> None:
    assert papertrail.__version__ == "0.1.0.dev0"


def test_error_codes_unique() -> None:
    values = [c.value for c in ErrorCode]
    assert len(values) == len(set(values))


def test_error_fields() -> None:
    err = PaperTrailError(ErrorCode.LOCKED, "库被占用", {"pid": 1})
    assert err.code == "locked"
    assert err.message == "库被占用"
    assert err.details == {"pid": 1}
