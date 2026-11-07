from pathlib import Path

import pytest

from ancilla_bot.tools import workspace_io as ws


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root))
    return root


@pytest.mark.parametrize("path", ["../secret.txt", "a/../../secret.txt", "<abs>"])
def test_paths_outside_workspace_are_rejected(root: Path, path: str):
    (root.parent / "secret.txt").write_text("s", encoding="utf-8")
    if path == "<abs>":
        path = str(root.parent / "secret.txt")
    for result in (
        ws.read_file(path),
        ws.write_file(path, "x"),
        ws.edit_file_safe(path, "append", content="x"),
        ws.trash_file(path),
        ws.move_file("a.txt", path),
        ws.list_workspace(path),
        ws.workspace_inventory(path),
    ):
        assert "workspace 以下のみ" in result
    assert (root.parent / "secret.txt").read_text(encoding="utf-8") == "s"


def test_user_md_is_read_only_for_all_writers(root: Path):
    (root / "USER.md").write_text("u", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")
    for result in (
        ws.write_file("user.md", "x"),
        ws.edit_file_safe("USER.md", "append", content="x"),
        ws.trash_file("USER.md"),
        ws.move_file("USER.md", "b.md"),
        ws.move_file("a.txt", "sub/USER.md"),
    ):
        assert "projection" in result
    assert (root / "USER.md").read_text(encoding="utf-8") == "u"
    assert ws.read_file("USER.md") == "u"


def test_read_file_truncates_by_max_lines(root: Path):
    (root / "n.txt").write_text("".join(f"{i}\n" for i in range(5)), encoding="utf-8")
    assert ws.read_file("n.txt", max_lines=2) == "0\n1\n\n... (truncated, max_lines=2)"
    assert ws.read_file("n.txt") == "0\n1\n2\n3\n4\n"
    assert "存在しません" in ws.read_file("missing.txt")


def test_edit_append_creates_then_string_and_line_replace(root: Path):
    assert ws.edit_file_safe("d/n.md", "append", content="a\nb\nc\n").startswith("追記完了")
    assert ws.edit_file_safe("d/n.md", "replace", old="b", new="B").startswith("置換完了")
    assert ws.edit_file_safe("d/n.md", "replace", start_line=3, end_line=3, new="C").startswith("置換完了")
    assert (root / "d" / "n.md").read_text(encoding="utf-8") == "a\nB\nC\n"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"operation": "overwrite", "content": "x"},
        {"operation": "replace", "old": "zzz", "new": "y"},
        {"operation": "replace", "old": "  ", "new": "y"},
        {"operation": "replace", "start_line": 2, "end_line": 1, "new": "y"},
        {"operation": "replace", "start_line": 1, "end_line": 9, "new": "y"},
        {"operation": "append", "content": "x" * (ws.MAX_EDIT_CONTENT_CHARS + 1)},
    ],
)
def test_edit_rejects_invalid_operations_without_writing(root: Path, kwargs):
    (root / "n.md").write_text("a\nb\n", encoding="utf-8")
    assert ws.edit_file_safe("n.md", **kwargs).startswith("Error")
    assert (root / "n.md").read_text(encoding="utf-8") == "a\nb\n"


def test_replace_requires_existing_file(root: Path):
    assert "append を使って" in ws.edit_file_safe("nope.md", "replace", old="a", new="b")
    assert not (root / "nope.md").exists()


def test_trash_moves_into_dot_trash_and_refuses_trash_contents(root: Path):
    (root / "a.txt").write_text("a", encoding="utf-8")
    result = ws.trash_file("a.txt")
    assert result.startswith("Moved to .trash")
    assert not (root / "a.txt").exists()
    trashed = list((root / ".trash").iterdir())
    assert [p.read_text(encoding="utf-8") for p in trashed] == ["a"]
    assert "既に .trash" in ws.trash_file(f".trash/{trashed[0].name}")


def test_trash_same_name_twice_keeps_both(root: Path):
    for body in ("1", "2"):
        (root / "a.txt").write_text(body, encoding="utf-8")
        ws.trash_file("a.txt")
    assert sorted(p.read_text(encoding="utf-8") for p in (root / ".trash").iterdir()) == ["1", "2"]


def test_move_never_overwrites(root: Path):
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    assert "既に存在" in ws.move_file("a.txt", "b.txt")
    assert (root / "b.txt").read_text(encoding="utf-8") == "b"
    assert ws.move_file("a.txt", "sub/c.txt") == "Moved a.txt -> sub/c.txt"
    assert (root / "sub" / "c.txt").read_text(encoding="utf-8") == "a"


def test_list_and_inventory_return_workspace_relative_paths(root: Path):
    (root / "sub").mkdir()
    (root / "sub" / "x.md").write_text("abc", encoding="utf-8")
    (root / "top.md").write_text("", encoding="utf-8")
    sep = "\\" if "\\" in str(Path("a/b")) else "/"
    assert ws.list_workspace().splitlines() == ["sub/", f"sub{sep}x.md", "top.md"]
    assert ws.list_workspace(max_entries=1).splitlines() == ["sub/"]
    assert f"sub{sep}x.md\t3" in ws.workspace_inventory("sub").splitlines()
    assert ws.read_file(f"sub{sep}x.md") == "abc"
