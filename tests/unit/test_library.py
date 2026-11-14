from __future__ import annotations

import os
import threading
import tomllib
from pathlib import Path

import pytest

from papernest.core import library as library_mod
from papernest.core.errors import PaperNestError
from papernest.core.library import Library, atomic_write, render_config
from papernest.core.models import LibraryConfig

CK = "2024-ACSNano-Quantum-Dot-Array"


def touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


def test_create_and_open(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "new", "测试库")
    for d in ["notes", "papers", "text", "topics", "data", "vocab", "inbox", "exports"]:
        assert (lib.root / d).is_dir(), d
    assert (lib.root / ".papernest" / "trash").is_dir()
    assert (lib.root / "vocab" / "tags.yaml").is_file()
    again = Library.open(lib.root)
    assert again.config.library.name == "测试库"
    assert again.config == lib.config
    with pytest.raises(PaperNestError) as ei:
        Library.create(lib.root, "x")
    assert ei.value.code == "library_exists"


def test_config_render_roundtrip() -> None:
    cfg = LibraryConfig()
    cfg.library.name = 'He said "hi"\\ 你好'
    cfg.network.contact_email = "a@b.c"
    assert LibraryConfig.model_validate(tomllib.loads(render_config(cfg))) == cfg


def test_open_missing(tmp_path: Path) -> None:
    with pytest.raises(PaperNestError) as ei:
        Library.open(tmp_path)
    assert ei.value.code == "library_not_found"


def test_open_too_new(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "l", "n")
    lib.config.library.format_version = 99
    lib.save_config()
    with pytest.raises(PaperNestError) as ei:
        Library.open(lib.root)
    assert ei.value.code == "library_format_too_new"


def test_open_bad_config(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "l", "n")
    (lib.root / "papernest.toml").write_text("[library\nbroken", encoding="utf-8")
    with pytest.raises(PaperNestError) as ei:
        Library.open(lib.root)
    assert ei.value.code == "config_invalid"


def test_fixture_opens(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    assert len(lib.list_citekeys()) == 12
    assert lib.list_citekeys() == sorted(lib.list_citekeys())


def test_main_file_does_not_match_prefix_siblings(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    x = "2022-Nature-Hybrid-Membrane-Design"
    (lib.papers_dir / f"{x}.pdf").unlink()
    assert lib.main_file(x) is None  # X-2.pdf 不算 X 的
    assert lib.main_file(f"{x}-2") == lib.papers_dir / f"{x}-2.pdf"
    touch(lib.papers_dir / f"{x}-2_SI.pdf")
    assert lib.si_files(x) == []
    assert lib.files_of(x) == [lib.note_path(x)]


def test_si_files_sorted_by_number(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    assert [p.name for p in lib.si_files(CK)] == [f"{CK}_SI.pdf", f"{CK}_SI2.docx"]
    for n in ("_SI10.pdf", "_SI3.pdf"):
        touch(lib.papers_dir / f"{CK}{n}")
    assert [p.name for p in lib.si_files(CK)] == [
        f"{CK}_SI.pdf",
        f"{CK}_SI2.docx",
        f"{CK}_SI3.pdf",
        f"{CK}_SI10.pdf",
    ]
    assert lib.main_file(CK) == lib.papers_dir / f"{CK}.pdf"


def test_main_file_prefers_pdf(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "l", "n")
    touch(lib.papers_dir / "2024-A-B.docx")
    assert lib.main_file("2024-A-B") == lib.papers_dir / "2024-A-B.docx"
    touch(lib.papers_dir / "2024-A-B.pdf")
    found = lib.main_file("2024-A-B")
    assert found is not None and found.suffix == ".pdf"


def test_files_of_includes_text(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    touch(lib.text_path(CK))
    names = [p.name for p in lib.files_of(CK)]
    assert names == [f"{CK}.md", f"{CK}.pdf", f"{CK}_SI.pdf", f"{CK}_SI2.docx", f"{CK}.txt"]


@pytest.mark.parametrize("bad", ["../evil-x-y", "a/b", "", "2024-A", "x"])
def test_paths_reject_bad_citekey(small_lib_path: Path, bad: str) -> None:
    lib = Library.open(small_lib_path)
    for fn in (lib.note_path, lib.text_path, lib.main_file, lib.si_files, lib.files_of):
        with pytest.raises(PaperNestError) as ei:
            fn(bad)
        assert ei.value.code == "citekey_invalid"


def test_atomic_write_text_lf_and_bytes(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "f.txt"
    atomic_write(p, "a\nb\n中文")
    assert p.read_bytes() == "a\nb\n中文".encode()
    atomic_write(p, b"\x00\x01")
    assert p.read_bytes() == b"\x00\x01"
    assert [x.name for x in p.parent.iterdir()] == ["f.txt"]


def test_state_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "state.json"
    atomic_write(p, "old")

    def boom(src: object, dst: object) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(library_mod.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(p, "new")
    assert p.read_text() == "old"
    assert [x.name for x in tmp_path.iterdir()] == ["state.json"]


def test_atomic_write_retries_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "f.txt"
    real = os.replace
    calls = {"n": 0}

    def flaky(src: str, dst: str) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("busy")
        real(src, dst)

    monkeypatch.setattr(library_mod.os, "replace", flaky)
    atomic_write(p, "ok")
    assert p.read_text() == "ok" and calls["n"] == 3


def test_concurrent_writes_no_lost_update(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "l", "n")
    target = lib.root / "counter.txt"
    lib.atomic_write(target, "0")
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(25):
                with lib.write_lock():
                    v = int(target.read_text())
                    lib.atomic_write(target, str(v + 1))
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert target.read_text() == "50"


def test_write_lock_reentrant_and_timeout(tmp_path: Path) -> None:
    lib = Library.create(tmp_path / "l", "n")
    with lib.write_lock(), lib.write_lock():
        pass
    other = Library.open(lib.root)  # 另一个实例，等价于另一个进程
    with lib.write_lock():
        with pytest.raises(PaperNestError) as ei, other.write_lock(timeout=0.1):
            pass
        assert ei.value.code == "locked"
    with other.write_lock(timeout=1):
        pass


def test_trash_and_restore(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    files = lib.files_of(CK)
    d = lib.trash(files, "remove")
    assert d.parent == lib.state_dir / "trash" and d.name.endswith("-remove")
    assert lib.files_of(CK) == []
    assert (d / "notes" / f"{CK}.md").is_file()
    assert (d / "papers" / f"{CK}_SI2.docx").is_file()
    back = lib.restore(d)
    assert sorted(back) == sorted(files)
    assert lib.files_of(CK) == files
    assert not d.exists()


def test_trash_same_second_gets_distinct_dirs(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    a = lib.trash([lib.papers_dir / f"{CK}_SI.pdf"], "op")
    b = lib.trash([lib.papers_dir / f"{CK}_SI2.docx"], "op")
    assert a != b and a.is_dir() and b.is_dir()


def test_trash_rejects_outside_and_missing(small_lib_path: Path, tmp_path: Path) -> None:
    lib = Library.open(small_lib_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    with pytest.raises(PaperNestError):
        lib.trash([outside], "op")
    assert outside.exists()
    with pytest.raises(FileNotFoundError):
        lib.trash([lib.note_path(CK), lib.papers_dir / "nope.pdf"], "op")
    assert lib.note_path(CK).exists()  # 校验失败时不动任何文件
    with pytest.raises(PaperNestError):
        lib.trash([lib.state_dir / "state.db"], "op")


def test_restore_refuses_on_conflict(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    note = lib.note_path(CK)
    d = lib.trash([note, lib.papers_dir / f"{CK}.pdf"], "op")
    note.write_text("new")
    with pytest.raises(PaperNestError) as ei:
        lib.restore(d)
    assert ei.value.code == "file_exists"
    assert (d / "papers" / f"{CK}.pdf").exists()  # 整体拒绝，没有部分还原
    assert not (lib.papers_dir / f"{CK}.pdf").exists()


def test_restore_rejects_non_trash_dir(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    with pytest.raises(PaperNestError):
        lib.restore(lib.notes_dir)
    with pytest.raises(PaperNestError):
        lib.restore(lib.state_dir / "trash")


def test_upgrade_noop_at_current(small_lib_path: Path) -> None:
    lib = Library.open(small_lib_path)
    lib.upgrade()
    assert not (lib.state_dir / "backups").exists() or not any(
        (lib.state_dir / "backups").iterdir()
    )


def test_upgrade_runs_migrations_with_backup(
    small_lib_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = Library.open(small_lib_path)
    (lib.state_dir).mkdir(exist_ok=True)
    (lib.state_dir / "state.db").write_bytes(b"db")
    calls: list[int] = []

    def m1(lib: Library) -> None:
        calls.append(1)

    def m2(lib: Library) -> None:
        calls.append(2)

    monkeypatch.setattr(library_mod, "FORMAT_VERSION", 3)
    monkeypatch.setitem(library_mod.MIGRATIONS, 1, m1)
    monkeypatch.setitem(library_mod.MIGRATIONS, 2, m2)
    reopened = Library.open(small_lib_path)  # 打开时自动升级
    assert calls == [1, 2]
    assert reopened.config.library.format_version == 3
    assert Library.open(small_lib_path).config.library.format_version == 3
    assert calls == [1, 2]
    (backup,) = list((lib.state_dir / "backups").iterdir())
    assert len(list((backup / "notes").glob("*.md"))) == 12
    assert (backup / "state.db").read_bytes() == b"db"


def test_upgrade_missing_migration(small_lib_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(library_mod, "FORMAT_VERSION", 2)
    with pytest.raises(PaperNestError) as ei:
        Library.open(small_lib_path)
    assert ei.value.code == "not_supported"
